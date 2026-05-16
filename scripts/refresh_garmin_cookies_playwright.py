"""
Playwright ヘッドレスブラウザで Garmin Connect にログインし、
JWT_WEB 等の本物のセッションクッキーを取得するスクリプト。

cloudscraper では SSO クッキー（GARMIN-SSO）しか取れず、
connect.garmin.com が要求する JWT_WEB が取得できないため、
Playwright で実際のブラウザフローを再現する。

使い方:
  pip install playwright
  playwright install chromium --with-deps
  GARMIN_EMAIL=xxx GARMIN_PASSWORD=yyy python scripts/refresh_garmin_cookies_playwright.py
"""
import os
import sys
import time

EMAIL = os.environ.get("GARMIN_EMAIL", "")
PASSWORD = os.environ.get("GARMIN_PASSWORD", "")

if not EMAIL or not PASSWORD:
    print("❌ GARMIN_EMAIL / GARMIN_PASSWORD 環境変数が必要です")
    sys.exit(1)

SESSION_COOKIE_FILE = "/tmp/garmin_session_cookies.txt"
CONNECT_BASE = "https://connect.garmin.com"


def login_and_get_cookies():
    """Playwright ヘッドレスブラウザでログインしてクッキーを取得。"""
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("❌ Playwright が必要: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        page = context.new_page()

        try:
            print("[1] connect.garmin.com/signin に移動...")
            page.goto(f"{CONNECT_BASE}/signin", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            print(f"    URL: {page.url}")

            # SSO フォームを探す（iframe 内またはメインページ）
            email_filled = False

            # まず iframe を試す
            for frame in page.frames:
                if "sso.garmin.com" in frame.url or "gauth" in frame.url:
                    print(f"    SSO iframe found: {frame.url[:60]}")
                    try:
                        frame.fill('input[name="username"]', EMAIL, timeout=5000)
                        email_filled = True
                        print("[2] email 入力 (iframe)...")
                        # パスワードフィールドがあるか確認
                        try:
                            frame.fill('input[name="password"]', PASSWORD, timeout=3000)
                            print("    password 入力 (iframe)...")
                            frame.click('button[type="submit"]', timeout=3000)
                            print("[3] submit クリック (iframe)...")
                        except Exception:
                            # username only → click next
                            try:
                                frame.click('button[type="submit"], #login-btn-signin', timeout=3000)
                                time.sleep(1)
                                frame.fill('input[name="password"]', PASSWORD, timeout=5000)
                                frame.click('button[type="submit"]', timeout=3000)
                                print("[3] 2段階 submit クリック (iframe)...")
                            except Exception as e2:
                                print(f"    iframe submit failed: {e2}")
                        break
                    except Exception as e:
                        print(f"    iframe fill failed: {e}")

            if not email_filled:
                # メインページ直接
                print("[2] メインページでフォーム入力を試みる...")
                selectors_email = [
                    'input[name="username"]',
                    'input[type="email"]',
                    '#username',
                    'input[placeholder*="mail" i]',
                ]
                for sel in selectors_email:
                    try:
                        page.fill(sel, EMAIL, timeout=3000)
                        email_filled = True
                        print(f"    email 入力: {sel}")
                        break
                    except Exception:
                        continue

                if email_filled:
                    selectors_pwd = [
                        'input[name="password"]',
                        'input[type="password"]',
                        '#password',
                    ]
                    pwd_filled = False
                    for sel in selectors_pwd:
                        try:
                            page.fill(sel, PASSWORD, timeout=3000)
                            pwd_filled = True
                            print(f"    password 入力: {sel}")
                            break
                        except Exception:
                            continue

                    if not pwd_filled:
                        # username-only step
                        page.click('button[type="submit"]', timeout=5000)
                        time.sleep(2)
                        for sel in selectors_pwd:
                            try:
                                page.fill(sel, PASSWORD, timeout=5000)
                                pwd_filled = True
                                break
                            except Exception:
                                continue

                    page.click('button[type="submit"]', timeout=5000)
                    print("[3] submit クリック...")

            if not email_filled:
                raise RuntimeError("ログインフォームが見つかりませんでした")

            # ログイン後の遷移を待つ
            print("[4] ログイン完了待機...")
            try:
                page.wait_for_url("*connect.garmin.com/modern*", timeout=30000)
            except PWTimeout:
                # URL が変わらない場合でも cookies を確認
                print("    URL 変化なし。cookies を確認...")

            # JWT_WEB が設定されるまで待つ
            print("[5] JWT_WEB クッキー待機...")
            for i in range(30):
                cookies = context.cookies([CONNECT_BASE])
                jwt_cookie = next((c for c in cookies if c["name"] == "JWT_WEB"), None)
                if jwt_cookie:
                    print(f"    ✓ JWT_WEB 取得成功!")
                    break
                if i % 5 == 0:
                    print(f"    waiting... ({i}s)")
                time.sleep(1)
            else:
                print("    ⚠ JWT_WEB が30秒以内に設定されませんでした")
                print(f"    現在のURL: {page.url}")

            # 全 Garmin クッキーを収集
            all_cookies = context.cookies([
                CONNECT_BASE,
                "https://connectapi.garmin.com",
                "https://sso.garmin.com",
                "https://garmin.com",
            ])

            cookie_dict = {}
            for c in all_cookies:
                if "garmin.com" in c.get("domain", ""):
                    cookie_dict[c["name"]] = c["value"]

            print(f"    取得クッキー: {list(cookie_dict.keys())}")
            return cookie_dict

        except Exception as e:
            print(f"    エラー: {e}")
            # Screenshot for debugging
            try:
                page.screenshot(path="/tmp/garmin_login_error.png")
                print("    スクリーンショット: /tmp/garmin_login_error.png")
            except Exception:
                pass
            raise
        finally:
            browser.close()


def test_cookies(cookies: dict) -> bool:
    """クッキーが connect.garmin.com のAPIで使えるかテスト（JSON確認）。"""
    import requests

    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "NK": "NT",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    })

    test_cases = [
        (
            "Connect proxy (personal-information)",
            f"{CONNECT_BASE}/modern/proxy/userprofile-service/userprofile/personal-information",
            {},
        ),
        (
            "Connect proxy (activities)",
            f"{CONNECT_BASE}/modern/proxy/activitylist-service/activities/search/activities",
            {"start": "0", "limit": "1"},
        ),
    ]

    for label, url, params in test_cases:
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                try:
                    data = r.json()
                    print(f"    ✓ {label}: JSON OK ({list(data.keys())[:3] if isinstance(data, dict) else type(data).__name__})")
                    return True
                except Exception:
                    print(f"    ✗ {label}: 200 but not JSON (HTML redirect?)")
            else:
                print(f"    ✗ {label}: status {r.status_code}")
        except Exception as e:
            print(f"    ✗ {label}: {e}")

    return False


def main():
    print("=" * 60)
    print("  Garmin Cookie 取得ツール (Playwright)")
    print("=" * 60)

    cookies = None
    for attempt in range(3):
        try:
            cookies = login_and_get_cookies()
            if cookies and any(k in cookies for k in ("JWT_WEB", "GARMIN-SSO")):
                break
            print(f"  試行 {attempt+1}: 十分なクッキーが取得できませんでした")
        except Exception as e:
            print(f"  試行 {attempt+1} 失敗: {e}")
            if attempt < 2:
                wait = 30 * (attempt + 1)
                print(f"  {wait}秒待機して再試行...")
                time.sleep(wait)

    if not cookies:
        print("❌ クッキーの取得に失敗")
        sys.exit(1)

    print("\n[クッキーテスト中...]")
    valid = test_cookies(cookies)

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    with open(SESSION_COOKIE_FILE, "w") as f:
        f.write(cookie_str)

    print(f"\n✓ {len(cookies)}個のクッキーを {SESSION_COOKIE_FILE} に保存")
    print(f"  JWT_WEB: {'あり' if 'JWT_WEB' in cookies else 'なし'}")

    if not valid:
        print("⚠ クッキーのAPIテストに失敗。動作しない可能性があります。")
        # JWT_WEB なしでは意味がないので失敗扱い
        if "JWT_WEB" not in cookies:
            sys.exit(1)
    else:
        print("✓ 完了")


if __name__ == "__main__":
    main()
