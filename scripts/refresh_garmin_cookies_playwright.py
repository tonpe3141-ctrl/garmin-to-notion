"""
Hybrid: cloudscraper で SSO チケット取得 → Playwright で JWT_WEB を取得。

cloudscraper は SSO フォームログインを担当（ボット検知を回避）。
Playwright はチケット URL に移動して connect.garmin.com の JS に JWT_WEB を発行させる。
OAuth /exchange/user/2.0 も /preauthorized も一切呼ばない。

使い方:
  pip install cloudscraper playwright
  playwright install chromium --with-deps
  GARMIN_EMAIL=xxx GARMIN_PASSWORD=yyy python scripts/refresh_garmin_cookies_playwright.py
"""
import os
import re
import sys
import time

import requests

EMAIL = os.environ.get("GARMIN_EMAIL", "")
PASSWORD = os.environ.get("GARMIN_PASSWORD", "")

if not EMAIL or not PASSWORD:
    print("❌ GARMIN_EMAIL / GARMIN_PASSWORD 環境変数が必要です")
    sys.exit(1)

SSO_BASE = "https://sso.garmin.com/sso"
CONNECT_BASE = "https://connect.garmin.com"
SESSION_COOKIE_FILE = "/tmp/garmin_session_cookies.txt"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

SIGNIN_PARAMS = {
    "service": f"{CONNECT_BASE}/modern",
    "webhost": CONNECT_BASE,
    "source": f"{CONNECT_BASE}/modern",
    "redirectAfterAccountLoginUrl": f"{CONNECT_BASE}/modern",
    "redirectAfterAccountCreationUrl": f"{CONNECT_BASE}/modern",
    "gauthHost": SSO_BASE,
    "locale": "en_US",
    "id": "gauth-widget",
    "clientId": "GarminConnect",
    "embedWidget": "false",
    "generateExtraServiceTicket": "true",
    "generateTwoExtraServiceTickets": "false",
    "generateNoServiceTicket": "false",
    "createAccountShown": "true",
    "openCreateAccount": "false",
    "usernameShown": "false",
    "displayNameShown": "false",
    "consumeServiceTicket": "false",
    "initialFocus": "true",
    "rememberMeShown": "true",
    "rememberMeChecked": "false",
    "mobile": "false",
    "connectLegalTerms": "true",
}


def _make_session():
    """cloudscraper があれば使い、なければ requests で代替。"""
    try:
        import cloudscraper
        s = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin", "desktop": True}
        )
    except ImportError:
        print("  ⚠ cloudscraper 未インストール → requests で代替")
        s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def get_sso_ticket() -> tuple:
    """
    旧 SSO エンドポイント (sso.garmin.com/sso/signin) でログインし、
    (sso_cookies, ticket_url) を返す。

    ticket_url は connect.garmin.com/modern?ticket=ST-xxx 形式。
    """
    s = _make_session()

    print("[SSO-1] GET signin page...")
    r = s.get(f"{SSO_BASE}/signin", params=SIGNIN_PARAMS, timeout=20)
    r.raise_for_status()

    csrf = None
    for pat in [
        r'name="_csrf"\s+value="(.+?)"',
        r'name="_csrf" value="(.+?)"',
        r'"_csrf"\s*:\s*"(.+?)"',
    ]:
        m = re.search(pat, r.text)
        if m:
            csrf = m.group(1)
            break
    if not csrf:
        raise RuntimeError("CSRF トークンが見つかりません")
    print("      CSRF: OK")
    time.sleep(1)

    print("[SSO-2] POST credentials (allow_redirects=False)...")
    r = s.post(
        f"{SSO_BASE}/signin",
        params=SIGNIN_PARAMS,
        headers={"Referer": f"{SSO_BASE}/signin", "Origin": "https://sso.garmin.com"},
        data={"username": EMAIL, "password": PASSWORD, "embed": "false", "_csrf": csrf},
        timeout=30,
        allow_redirects=False,
    )
    print(f"      status={r.status_code}")

    ticket_url = None

    if r.status_code in (301, 302):
        loc = r.headers.get("Location", "")
        print(f"      Location: {loc[:100]}")
        if "ticket=" in loc or "connect.garmin.com" in loc:
            ticket_url = loc
        else:
            # ロケーションが別のSSOページならもう一段追う
            print("      → SSO 中間リダイレクト。再追跡...")
            r2 = s.get(loc, allow_redirects=False, timeout=15)
            loc2 = r2.headers.get("Location", "")
            if "ticket=" in loc2:
                ticket_url = loc2
            elif "connect.garmin.com" in loc2:
                ticket_url = loc2

    elif r.status_code == 200:
        m = re.search(r'ticket=(ST-[A-Za-z0-9\-_]+)', r.text)
        if m:
            ticket_url = f"{CONNECT_BASE}/modern?ticket={m.group(1)}"
            print(f"      Ticket from body: {m.group(1)[:40]}")
        else:
            print("      ⚠ 200 応答にチケットが見つかりません。allow_redirects=True で再試行...")
            r2 = s.post(
                f"{SSO_BASE}/signin",
                params=SIGNIN_PARAMS,
                headers={"Referer": f"{SSO_BASE}/signin", "Origin": "https://sso.garmin.com"},
                data={"username": EMAIL, "password": PASSWORD, "embed": "false", "_csrf": csrf},
                timeout=30,
                allow_redirects=True,
            )
            print(f"      Final URL: {r2.url}")
            m2 = re.search(r'ticket=(ST-[A-Za-z0-9\-_]+)', r2.url + " " + r2.text)
            if m2:
                ticket_url = f"{CONNECT_BASE}/modern?ticket={m2.group(1)}"
            elif "connect.garmin.com" in r2.url:
                ticket_url = r2.url

    if not ticket_url:
        raise RuntimeError(f"チケット URL が取得できませんでした (status={r.status_code})")

    sso_cookies = {}
    for c in s.cookies:
        if "garmin.com" in getattr(c, "domain", ""):
            sso_cookies[c.name] = c.value

    print(f"      SSO cookies: {list(sso_cookies.keys())}")
    return sso_cookies, ticket_url


def get_jwt_via_playwright(ticket_url: str, sso_cookies: dict) -> dict:
    """
    Playwright でチケット URL に移動し、connect.garmin.com の JS に
    JWT_WEB をセットさせて回収する。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ❌ Playwright 未インストール")
        return {}

    print(f"[PW-1] Navigate: {ticket_url[:80]}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )

        # SSO クッキーをコンテキストに注入
        for name, value in sso_cookies.items():
            for domain in [".garmin.com", ".sso.garmin.com", "sso.garmin.com"]:
                try:
                    context.add_cookies([{
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": "/",
                    }])
                except Exception:
                    pass

        page = context.new_page()

        try:
            page.goto(ticket_url, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print(f"      goto warning (continuing): {e}")

        print(f"      URL after nav: {page.url}")

        # JWT_WEB が現れるまで最大 30 秒待機
        print("[PW-2] Waiting for JWT_WEB...")
        jwt_found = False
        for i in range(30):
            cookies_now = context.cookies(["https://connect.garmin.com"])
            if any(c["name"] == "JWT_WEB" for c in cookies_now):
                print(f"      ✓ JWT_WEB 取得成功 ({i}s)")
                jwt_found = True
                break
            if i % 5 == 0:
                print(f"      waiting {i}s | URL: {page.url[:70]}")
            time.sleep(1)

        if not jwt_found:
            print(f"      ⚠ JWT_WEB が 30 秒以内に現れませんでした | URL: {page.url}")
            # スクリーンショット保存（デバッグ用）
            try:
                page.screenshot(path="/tmp/garmin_pw_debug.png")
                print("      スクリーンショット: /tmp/garmin_pw_debug.png")
            except Exception:
                pass

        # 全 Garmin クッキーを収集
        all_raw = context.cookies([
            "https://connect.garmin.com",
            "https://connectapi.garmin.com",
            "https://sso.garmin.com",
            "https://garmin.com",
        ])
        result = {
            c["name"]: c["value"]
            for c in all_raw
            if "garmin.com" in c.get("domain", "")
        }

        browser.close()
        return result


def test_cookies(cookies: dict) -> bool:
    """取得クッキーで JSON API をテスト。"""
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": UA,
        "NK": "NT",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })

    endpoints = [
        (
            "personal-information",
            f"{CONNECT_BASE}/modern/proxy/userprofile-service/userprofile/personal-information",
            {},
        ),
        (
            "activities",
            f"{CONNECT_BASE}/modern/proxy/activitylist-service/activities/search/activities",
            {"start": "0", "limit": "1"},
        ),
    ]

    for label, url, params in endpoints:
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                try:
                    data = r.json()
                    keys = list(data.keys())[:3] if isinstance(data, dict) else type(data).__name__
                    print(f"  ✓ {label}: JSON OK {keys}")
                    return True
                except Exception:
                    print(f"  ✗ {label}: 200 だが JSON ではない (HTML リダイレクト?)")
            else:
                print(f"  ✗ {label}: status {r.status_code}")
        except Exception as e:
            print(f"  ✗ {label}: {e}")

    return False


def main():
    print("=" * 60)
    print("  Garmin Cookie 取得 (cloudscraper SSO + Playwright JWT)")
    print("=" * 60)

    # SSO チケット取得（最大 3 回）
    sso_cookies, ticket_url = {}, None
    for attempt in range(3):
        try:
            sso_cookies, ticket_url = get_sso_ticket()
            if ticket_url:
                break
        except Exception as e:
            print(f"  SSO 試行 {attempt+1} 失敗: {e}")
            if attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"  {wait}s 待機して再試行...")
                time.sleep(wait)

    if not ticket_url:
        print("❌ SSO チケット取得に失敗しました")
        sys.exit(1)

    print(f"\nTicket URL: {ticket_url[:100]}")

    # Playwright で JWT_WEB 取得
    pw_cookies = get_jwt_via_playwright(ticket_url, sso_cookies)

    # SSO + Playwright クッキーをマージ（Playwright 優先）
    merged = {**sso_cookies, **pw_cookies}
    print(f"\n取得クッキー: {list(merged.keys())}")

    # API テスト
    print("\n[API テスト]")
    valid = test_cookies(merged)

    # ファイルに保存
    cookie_str = "; ".join(f"{k}={v}" for k, v in merged.items())
    with open(SESSION_COOKIE_FILE, "w") as f:
        f.write(cookie_str)

    print(f"\n✓ {len(merged)}個のクッキーを {SESSION_COOKIE_FILE} に保存")
    print(f"  JWT_WEB: {'あり' if 'JWT_WEB' in merged else 'なし'}")

    if not valid or "JWT_WEB" not in merged:
        print("⚠ API テスト失敗または JWT_WEB なし")
        sys.exit(1)

    print("✓ 完了")


if __name__ == "__main__":
    main()
