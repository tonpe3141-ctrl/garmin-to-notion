"""
cloudscraper で Garmin Connect のセッションクッキーを自動取得するスクリプト。

OAuth / garth を一切使わず、ブラウザセッションクッキー（JWT_WEB等）を生成する。
GitHub Actions の /oauth/exchange/user/2.0 レート制限を完全回避する。
取得したクッキーは GarminCookieClient で使用する。

使い方:
  GARMIN_EMAIL=xxx GARMIN_PASSWORD=yyy python scripts/refresh_garmin_cookies.py
"""
import os
import re
import sys
import time

try:
    import cloudscraper
except ImportError:
    print("❌ cloudscraper が必要: pip install cloudscraper")
    sys.exit(1)

EMAIL = os.environ.get("GARMIN_EMAIL", "")
PASSWORD = os.environ.get("GARMIN_PASSWORD", "")

if not EMAIL or not PASSWORD:
    print("❌ GARMIN_EMAIL / GARMIN_PASSWORD 環境変数が必要です")
    sys.exit(1)

SSO_BASE = "https://sso.garmin.com/sso"
CONNECT_BASE = "https://connect.garmin.com"
CONNECTAPI = "https://connectapi.garmin.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

# connect.garmin.com をサービスターゲットにしたSSOパラメータ
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

SESSION_COOKIE_FILE = "/tmp/garmin_session_cookies.txt"


def create_scraper():
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "desktop": True}
    )
    s.headers.update({"User-Agent": UA})
    return s


def login_and_get_cookies(scraper) -> dict:
    """SSO loginしてconnect.garmin.comのセッションクッキーを取得する。"""

    print("[1] GET SSO signin page...")
    r = scraper.get(f"{SSO_BASE}/signin", params=SIGNIN_PARAMS, timeout=20)
    r.raise_for_status()

    # CSRF取得（複数パターン対応）
    csrf = None
    for pattern in [
        r'name="_csrf"\s+value="(.+?)"',
        r'name="_csrf" value="(.+?)"',
        r'"_csrf"\s*:\s*"(.+?)"',
    ]:
        m = re.search(pattern, r.text)
        if m:
            csrf = m.group(1)
            break
    if not csrf:
        raise RuntimeError("CSRF トークンが見つかりませんでした")
    print(f"    CSRF: OK")
    time.sleep(1)

    print("[2] POST login form...")
    r = scraper.post(
        f"{SSO_BASE}/signin",
        params=SIGNIN_PARAMS,
        headers={
            "Referer": f"{SSO_BASE}/signin",
            "Origin": "https://sso.garmin.com",
        },
        data={
            "username": EMAIL,
            "password": PASSWORD,
            "embed": "false",
            "_csrf": csrf,
        },
        timeout=30,
        allow_redirects=True,
    )

    if r.status_code == 429:
        raise RuntimeError("429 Rate Limited at SSO login")
    if r.status_code not in (200, 302):
        raise RuntimeError(f"ログイン失敗: status={r.status_code}")

    print(f"    Final URL: {r.url}")

    # connect.garmin.com にリダイレクトされていない場合、ticketを手動で追跡
    if "connect.garmin.com" not in r.url:
        ticket = None
        for pattern in [r'ticket=([A-Za-z0-9\-_]+)', r'ST-[A-Za-z0-9\-_]+']:
            m = re.search(pattern, r.text)
            if m:
                ticket = m.group(0) if "ST-" in pattern else m.group(1)
                break

        if ticket:
            print(f"    Ticket found: {ticket[:20]}...")
            print("[3] Following redirect to connect.garmin.com...")
            r = scraper.get(
                f"{CONNECT_BASE}/modern",
                params={"ticket": ticket},
                timeout=20,
                allow_redirects=True,
            )
            print(f"    Connect URL: {r.url}, Status: {r.status_code}")
        else:
            print("    Warning: No ticket found, proceeding with current cookies")

    # 全Garminクッキーを収集
    cookies = {}
    for c in scraper.cookies:
        if "garmin.com" in getattr(c, "domain", ""):
            cookies[c.name] = c.value

    print(f"    Cookies: {list(cookies.keys())}")
    return cookies


def test_cookies(cookies: dict) -> bool:
    """取得したクッキーでAPIアクセスをテストする。"""
    import requests

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": UA,
        "NK": "NT",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })

    # Proxy経由テスト（connect.garmin.com/modern/proxy/...）
    endpoints_to_try = [
        (
            "Connect proxy (userinfo)",
            f"{CONNECT_BASE}/modern/proxy/userprofile-service/userprofile/personal-information",
            {},
        ),
        (
            "Connect proxy (activities)",
            f"{CONNECT_BASE}/modern/proxy/activitylist-service/activities/search/activities",
            {"start": "0", "limit": "1"},
        ),
        (
            "Connectapi direct (activities)",
            f"{CONNECTAPI}/activitylist-service/activities/search/activities",
            {"start": "0", "limit": "1"},
        ),
    ]

    for label, url, params in endpoints_to_try:
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                print(f"    ✓ {label}: OK")
                return True
            else:
                print(f"    ✗ {label}: status {r.status_code}")
        except Exception as e:
            print(f"    ✗ {label}: {e}")

    return False


def main():
    print("=" * 60)
    print("  Garmin Cookie 取得ツール（OAuth exchange 不使用）")
    print("=" * 60)

    scraper = create_scraper()
    cookies = None

    for attempt in range(3):
        try:
            cookies = login_and_get_cookies(scraper)
            if cookies:
                break
        except RuntimeError as e:
            if "429" in str(e) and attempt < 2:
                wait = 60 * (attempt + 1)
                print(f"  Rate limited. {wait}s 待機して再試行...")
                time.sleep(wait)
                scraper = create_scraper()
            else:
                print(f"❌ ログイン失敗: {e}")
                sys.exit(1)

    if not cookies:
        print("❌ クッキーが取得できませんでした")
        sys.exit(1)

    print("\n[テスト中...]")
    valid = test_cookies(cookies)

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    with open(SESSION_COOKIE_FILE, "w") as f:
        f.write(cookie_str)
    print(f"\n✓ {len(cookies)}個のクッキーを {SESSION_COOKIE_FILE} に保存")

    if not valid:
        print("⚠ クッキーのテストに失敗。動作しない可能性があります。")
        sys.exit(1)

    print("✓ 完了")


if __name__ == "__main__":
    main()
