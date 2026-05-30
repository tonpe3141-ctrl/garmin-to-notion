"""
Playwright で Garmin Connect に直接ログインして JWT_WEB を取得する。

戦略（優先度順）:
  1. Playwright 直接ブラウザログイン（connect.garmin.com/app → SSO フォーム入力）
  2. cloudscraper で SSO チケット取得 → Playwright でチケット URL を処理（フォールバック）

OAuth /exchange/user/2.0 も /preauthorized も一切呼ばない。

使い方:
  pip install cloudscraper playwright
  playwright install chromium --with-deps
  GARMIN_EMAIL=xxx GARMIN_PASSWORD=yyy python scripts/refresh_garmin_cookies_playwright.py
"""
import json
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
    "service": f"{CONNECT_BASE}/app",
    "webhost": CONNECT_BASE,
    "source": f"{CONNECT_BASE}/app",
    "redirectAfterAccountLoginUrl": f"{CONNECT_BASE}/app",
    "redirectAfterAccountCreationUrl": f"{CONNECT_BASE}/app",
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

# garth 互換のエンベッドウィジェット SSO（/app が失敗した場合のフォールバック用）
SIGNIN_PARAMS_EMBED = {
    "id": "gauth-widget",
    "embedWidget": "true",
    "gauthHost": f"{SSO_BASE}/embed",
    "service": f"{SSO_BASE}/embed",
    "source": f"{SSO_BASE}/embed",
    "redirectAfterAccountLoginUrl": f"{SSO_BASE}/embed",
    "redirectAfterAccountCreationUrl": f"{SSO_BASE}/embed",
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


def _do_sso_login(s, params: dict) -> tuple:
    """
    SSO ログインを実行し (sso_cookies, ticket_url) を返す。
    失敗時は (sso_cookies, None) を返す。
    """
    print("[SSO-1] GET signin page...")
    r = s.get(f"{SSO_BASE}/signin", params=params, timeout=20)
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

    is_embed = params.get("embedWidget") == "true"
    embed_val = "true" if is_embed else "false"

    print("[SSO-2] POST credentials (allow_redirects=False)...")
    r = s.post(
        f"{SSO_BASE}/signin",
        params=params,
        headers={"Referer": f"{SSO_BASE}/signin", "Origin": "https://sso.garmin.com"},
        data={"username": EMAIL, "password": PASSWORD, "embed": embed_val, "_csrf": csrf},
        timeout=30,
        allow_redirects=False,
    )
    print(f"      status={r.status_code}")

    ticket_url = None

    if r.status_code in (301, 302):
        loc = r.headers.get("Location", "")
        print(f"      Location: {loc[:100]}")
        if "ticket=" in loc or "connect.garmin.com" in loc or "sso.garmin.com" in loc:
            ticket_url = loc
        else:
            print("      → SSO 中間リダイレクト。再追跡...")
            r2 = s.get(loc, allow_redirects=False, timeout=15)
            loc2 = r2.headers.get("Location", "")
            if "ticket=" in loc2:
                ticket_url = loc2
            elif "garmin.com" in loc2:
                ticket_url = loc2

    elif r.status_code == 200:
        # チケットを body から探す（embed フローなど）
        m = re.search(r'ticket=(ST-[A-Za-z0-9\-_]+)', r.text)
        if m:
            ticket = m.group(1)
            # embed フローなら SSO ドメインのまま；それ以外は /app へ
            if is_embed:
                ticket_url = f"{SSO_BASE}/embed?ticket={ticket}"
            else:
                ticket_url = f"{CONNECT_BASE}/app?ticket={ticket}"
            print(f"      Ticket from body: {ticket[:40]}")
        else:
            print("      ⚠ 200 応答にチケットが見つかりません。allow_redirects=True で再試行...")
            r2 = s.post(
                f"{SSO_BASE}/signin",
                params=params,
                headers={"Referer": f"{SSO_BASE}/signin", "Origin": "https://sso.garmin.com"},
                data={"username": EMAIL, "password": PASSWORD, "embed": embed_val, "_csrf": csrf},
                timeout=30,
                allow_redirects=True,
            )
            print(f"      Final URL: {r2.url}")
            m2 = re.search(r'ticket=(ST-[A-Za-z0-9\-_]+)', r2.url + " " + r2.text)
            if m2:
                ticket_url = f"{CONNECT_BASE}/app?ticket={m2.group(1)}"
            elif "connect.garmin.com" in r2.url:
                ticket_url = r2.url

    sso_cookies = {}
    for c in s.cookies:
        if "garmin.com" in getattr(c, "domain", ""):
            sso_cookies[c.name] = c.value

    print(f"      SSO cookies: {list(sso_cookies.keys())}")
    return sso_cookies, ticket_url


def get_sso_ticket() -> tuple:
    """
    SSO エンドポイントでログインし (sso_cookies, ticket_url) を返す。

    戦略:
      1. SIGNIN_PARAMS (/app サービス) で試行
      2. 失敗なら SIGNIN_PARAMS_EMBED (garth 互換 embed) で再試行
    """
    s = _make_session()

    sso_cookies, ticket_url = _do_sso_login(s, SIGNIN_PARAMS)

    if not ticket_url:
        print("      → /app SSO 失敗。embed フローで再試行...")
        s2 = _make_session()
        sso_cookies, ticket_url = _do_sso_login(s2, SIGNIN_PARAMS_EMBED)

    # レガシーフォールバック: /app への手動補完
    if ticket_url and "/modern?ticket=" in ticket_url:
        ticket_url = ticket_url.replace("/modern?ticket=", "/app?ticket=")

    if not ticket_url:
        raise RuntimeError("チケット URL が取得できませんでした")

    return sso_cookies, ticket_url


def get_jwt_via_browser_login() -> dict:
    """
    Playwright で connect.garmin.com/app に直接アクセスし、
    SSO ログインフォームにメール/パスワードを入力して JWT_WEB を取得する。

    SSO チケット取得 → チケット URL 移動というフローを経由せず、
    実際のブラウザ操作でログインするため最も確実。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ❌ Playwright 未インストール")
        return {}

    print("[PW-Direct] Starting direct browser login...")

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
        page = context.new_page()
        jwt_found = False

        try:
            # Step 1: connect.garmin.com/app に移動 → SSO ログインページにリダイレクト
            print(f"[PW-D1] Navigate to {CONNECT_BASE}/app ...")
            try:
                page.goto(f"{CONNECT_BASE}/app", wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"      goto warning: {e}")
            print(f"      URL after nav: {page.url}")

            # SSO ページに着いていなければ直接 SSO ログイン URL へ
            if "sso.garmin.com" not in page.url and "signin" not in page.url:
                sso_url = (
                    f"{SSO_BASE}/signin"
                    f"?service={CONNECT_BASE}/app"
                    f"&clientId=GarminConnect"
                    f"&gauthHost={SSO_BASE}"
                    f"&generateExtraServiceTicket=true"
                    f"&embedWidget=false"
                )
                print(f"[PW-D2] Not on SSO page. Navigate to SSO signin directly...")
                try:
                    page.goto(sso_url, wait_until="domcontentloaded", timeout=20000)
                except Exception as e:
                    print(f"      goto warning: {e}")
                print(f"      URL: {page.url}")

            # Step 2: ログインフォームへの入力
            print("[PW-D3] Filling login form...")
            email_selectors = [
                'input[name="username"]', 'input[id="username"]',
                'input[type="email"]', '#email',
            ]
            password_selectors = [
                'input[name="password"]', 'input[id="password"]',
                'input[type="password"]',
            ]
            submit_selectors = [
                'button[type="submit"]', 'input[type="submit"]',
                'button#login-btn-signin', '#login-btn-signin',
                'a[id="login-btn-signin"]',
            ]

            email_filled = False
            for sel in email_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.fill(EMAIL)
                        email_filled = True
                        print(f"      email filled ({sel})")
                        break
                except Exception:
                    pass

            if not email_filled:
                print("      ⚠ email field not found; taking screenshot")
                try:
                    page.screenshot(path="/tmp/garmin_pw_debug.png")
                    print("      スクリーンショット: /tmp/garmin_pw_debug.png")
                except Exception:
                    pass

            pw_filled = False
            for sel in password_selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.fill(PASSWORD)
                        pw_filled = True
                        print(f"      password filled ({sel})")
                        break
                except Exception:
                    pass

            if email_filled and pw_filled:
                time.sleep(0.5)  # フォーム入力後の短い待機
                submitted = False
                for sel in submit_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el and el.is_visible():
                            el.click()
                            submitted = True
                            print(f"      submit clicked ({sel})")
                            break
                    except Exception:
                        pass
                if not submitted:
                    page.keyboard.press("Enter")
                    print("      submit: pressed Enter")
            else:
                print("      ⚠ フォーム入力失敗。ログインをスキップします。")

            # Step 3: JWT_WEB が設定されるまで最大 60 秒待機
            print("[PW-D4] Waiting for JWT_WEB (up to 60s)...")
            for i in range(60):
                cookies_now = context.cookies(["https://connect.garmin.com"])
                if any(c["name"] == "JWT_WEB" for c in cookies_now):
                    print(f"      ✓ JWT_WEB 取得成功 ({i}s) | URL: {page.url[:60]}")
                    jwt_found = True
                    break
                if i % 10 == 0:
                    print(f"      waiting {i}s | URL: {page.url[:70]}")
                time.sleep(1)

            if not jwt_found:
                print(f"      ⚠ JWT_WEB が取得できませんでした | URL: {page.url}")
                try:
                    page.screenshot(path="/tmp/garmin_pw_debug.png")
                    print("      スクリーンショット: /tmp/garmin_pw_debug.png")
                except Exception:
                    pass
            else:
                # JWT_WEB 取得後にデータプリフェッチ
                try:
                    prefetch_garmin_data(page)
                except Exception as _pe:
                    print(f"  ⚠ プリフェッチ失敗（続行）: {_pe}")

        except Exception as e:
            print(f"      ⚠ Direct login error: {e}")

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


def get_jwt_via_playwright(ticket_url: str, sso_cookies: dict) -> dict:
    """
    Playwright でチケット URL または /app/home に移動し、connect.garmin.com の JS に
    JWT_WEB をセットさせて回収する。

    戦略:
      1. チケット URL (/app?ticket=... など) に移動
      2. JWT_WEB が現れなければ /app/home に移動（新アプリ経由で SSO 再認証）
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

        # SSO クッキーをコンテキストに注入（全 Garmin ドメイン）
        for name, value in sso_cookies.items():
            for domain in [".garmin.com", ".sso.garmin.com", "sso.garmin.com",
                           ".connect.garmin.com", "connect.garmin.com"]:
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

        # connect.garmin.com から返される JSON API レスポンスを収集
        discovered_api_paths: dict = {}

        def _on_response(response):
            try:
                url = response.url
                if "connect.garmin.com" in url and response.status == 200:
                    ct = response.headers.get("content-type", "")
                    if "application/json" in ct:
                        # パスのみを抽出（クエリを除く）
                        path = url.replace("https://connect.garmin.com", "").split("?")[0]
                        discovered_api_paths[path] = url
            except Exception:
                pass

        page.on("response", _on_response)

        try:
            page.goto(ticket_url, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print(f"      goto warning (continuing): {e}")

        print(f"      URL after nav: {page.url}")

        # Phase 1: /modern?ticket=... で JWT_WEB を待機（最大15秒）
        print("[PW-2] Phase 1: Waiting for JWT_WEB at ticket URL (15s)...")
        jwt_found = False
        for i in range(15):
            cookies_now = context.cookies(["https://connect.garmin.com"])
            if any(c["name"] == "JWT_WEB" for c in cookies_now):
                print(f"      ✓ JWT_WEB 取得成功 (Phase 1, {i}s)")
                jwt_found = True
                break
            time.sleep(1)

        # Phase 2: JWT_WEB がなければ /app/home に移動（新 Garmin Connect アプリ）
        # CASTGC などの SSO クッキーがあれば、/app/home へのアクセスで
        # SSO が自動的にチケットを発行して JWT_WEB がセットされる。
        if not jwt_found:
            app_home_url = f"{CONNECT_BASE}/app/home"
            print(f"[PW-3] Phase 2: Navigating to new app ({app_home_url})...")
            try:
                page.goto(app_home_url, wait_until="networkidle", timeout=45000)
            except Exception as e:
                print(f"      goto warning (continuing): {e}")
            print(f"      URL after nav: {page.url}")

            for i in range(30):
                cookies_now = context.cookies(["https://connect.garmin.com"])
                if any(c["name"] == "JWT_WEB" for c in cookies_now):
                    print(f"      ✓ JWT_WEB 取得成功 (Phase 2, {i}s)")
                    jwt_found = True
                    break
                if i % 5 == 0:
                    print(f"      waiting {i}s | URL: {page.url[:70]}")
                time.sleep(1)

        if not jwt_found:
            print(f"      ⚠ JWT_WEB が取得できませんでした | URL: {page.url}")
            # スクリーンショット保存（デバッグ用）
            try:
                page.screenshot(path="/tmp/garmin_pw_debug.png")
                print("      スクリーンショット: /tmp/garmin_pw_debug.png")
            except Exception:
                pass

        # JWT_WEB 取得後にアクティビティデータを事前取得（Python から /gc-api/ が 403 になるため）
        if jwt_found:
            try:
                prefetch_garmin_data(page)
            except Exception as _pe:
                print(f"  ⚠ プリフェッチ失敗（続行）: {_pe}")

        # JWT_WEB 取得後、SPA の API コールが発生するまで少し待つ（パス発見用）
        if jwt_found and discovered_api_paths:
            time.sleep(3)  # SPA が追加の API コールをするのを待つ

        # 発見した API パスを保存
        if discovered_api_paths:
            import json as _json
            print(f"\n[API パス発見] {len(discovered_api_paths)} 件:")
            for p in list(discovered_api_paths.keys())[:10]:
                print(f"    {p}")
            try:
                with open("/tmp/garmin_api_paths.json", "w") as _f:
                    _json.dump(discovered_api_paths, _f)
                print("  ✓ /tmp/garmin_api_paths.json に保存しました")
            except Exception as _e:
                print(f"  ⚠ API パス保存失敗: {_e}")

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


def prefetch_garmin_data(page, activities_limit: int = 200) -> bool:
    """
    Playwright のブラウザコンテキストから活動データを事前取得して
    /tmp/garmin_prefetch.json に保存する。

    SPA が自然に行う最初の API コールをインターセプトし、
    そのリクエストヘッダーをキャプチャして後続のページネーションに使用する。
    """
    print("\n[データ事前取得] SPA API コールをインターセプト中...")

    intercepted_activities: list = []
    intercepted_splits: dict = {}
    spa_request_headers: dict = {}  # SPA が使うリクエストヘッダー（後続 fetch に再利用）

    def _capture_response(response):
        try:
            url = response.url
            if "connect.garmin.com" not in url or response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "application/json" not in ct:
                return
            path = url.replace("https://connect.garmin.com", "").split("?")[0]
            if "activitylist-service/activities/search/activities" in path:
                try:
                    data = response.json()
                    if isinstance(data, list):
                        intercepted_activities.extend(data)
                        print(f"  ✓ intercepted: +{len(data)} (total {len(intercepted_activities)})")
                except Exception:
                    pass
            elif "activity-service/activity/" in path and "/splits" in path:
                try:
                    aid = path.split("/activity/")[1].split("/")[0]
                    data = response.json()
                    if data:
                        intercepted_splits[aid] = data
                except Exception:
                    pass
        except Exception:
            pass

    def _capture_request(request):
        if "activitylist-service/activities/search/activities" in request.url:
            if not spa_request_headers:
                spa_request_headers.update({
                    k: v for k, v in dict(request.headers).items()
                    if k.lower() not in ("cookie", "content-length")
                })
                print(f"  ℹ SPA request headers: {list(spa_request_headers.keys())}")

    page.on("response", _capture_response)
    page.on("request", _capture_request)

    # activities ページへ移動して初期データを取得
    try:
        page.goto(f"{CONNECT_BASE}/app/activities", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)
    except Exception as e:
        print(f"  ⚠ activities ページ移動エラー: {e}")

    # SPA のヘッダーを使ってページネーション（追加の活動を取得）
    if spa_request_headers and len(intercepted_activities) > 0:
        print(f"  → SPA ヘッダーで追加ページネーション中 (現在 {len(intercepted_activities)} 件)...")
        headers_js = json.dumps(spa_request_headers)
        while len(intercepted_activities) < activities_limit:
            start = len(intercepted_activities)
            try:
                result = page.evaluate(f"""
                    async () => {{
                        const r = await fetch(
                            '/gc-api/activitylist-service/activities/search/activities?start={start}&limit=50',
                            {{credentials:'include', headers: {headers_js}}}
                        );
                        if (!r.ok) return {{error: r.status}};
                        return await r.json();
                    }}
                """)
                if not result or isinstance(result, dict):
                    print(f"  ✗ ページネーション失敗: {result}")
                    break
                if not isinstance(result, list) or len(result) == 0:
                    break
                intercepted_activities.extend(result)
                print(f"  ✓ ページネーション: +{len(result)} (total {len(intercepted_activities)})")
                if len(result) < 50:
                    break
            except Exception as e:
                print(f"  ✗ ページネーションエラー: {e}")
                break
    else:
        # SPA ヘッダーが取れない場合はスクロールで試みる
        scroll_count = 0
        cutoff = time.time() + 60
        while len(intercepted_activities) < activities_limit and time.time() < cutoff:
            try:
                page.evaluate("document.querySelector('main, [class*=\"activity\"], body').scrollTop = 999999 || window.scrollTo(0, 999999)")
                page.wait_for_timeout(2000)
                scroll_count += 1
                if scroll_count > 15:
                    break
            except Exception:
                break

    print(f"  → 合計: {len(intercepted_activities)} activities, {len(intercepted_splits)} splits")

    if not intercepted_activities:
        print("  ✗ アクティビティデータが取得できませんでした")
        return False

    prefetch = {
        "activities": intercepted_activities[:activities_limit],
        "splits": intercepted_splits,
        "details": {},
    }
    try:
        with open("/tmp/garmin_prefetch.json", "w") as pf:
            json.dump(prefetch, pf)
        print(f"  ✓ /tmp/garmin_prefetch.json に保存 ({len(prefetch['activities'])} activities)")
        return True
    except Exception as e:
        print(f"  ✗ 保存失敗: {e}")
        return False


def test_cookies(cookies: dict) -> bool:
    """取得クッキーで JSON API をテスト（複数エンドポイント + JWT_WEB Bearer）。"""
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": UA,
        "NK": "NT",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Origin": "https://connect.garmin.com",
        "Referer": "https://connect.garmin.com/app/home",
    })

    jwt_web = cookies.get("JWT_WEB", "")

    endpoints = [
        # 新アプリ BFF (/gc-api/ プレフィックス) を最優先
        ("userinfo (gc-api)",        f"{CONNECT_BASE}/gc-api/userprofile-service/userprofile/user-settings/", {}, {}),
        ("activities (gc-api)",      f"{CONNECT_BASE}/gc-api/activitylist-service/activities/search/activities", {"start": "0", "limit": "1"}, {}),
        # 旧直接パス
        ("userinfo (direct)",        f"{CONNECT_BASE}/userprofile-service/userprofile/personal-information", {}, {}),
        ("activities (direct)",      f"{CONNECT_BASE}/activitylist-service/activities/search/activities", {"start": "0", "limit": "1"}, {}),
        ("userinfo (proxy)",         f"{CONNECT_BASE}/modern/proxy/userprofile-service/userprofile/personal-information", {}, {}),
        ("activities (proxy)",       f"{CONNECT_BASE}/modern/proxy/activitylist-service/activities/search/activities", {"start": "0", "limit": "1"}, {}),
    ]
    # JWT_WEB を Bearer として connectapi を試す（最終手段）
    if jwt_web:
        endpoints += [
            ("userinfo (connectapi+JWT)",
             "https://connectapi.garmin.com/userprofile-service/userprofile/personal-information",
             {}, {"Authorization": f"Bearer {jwt_web}"}),
            ("activities (connectapi+JWT)",
             "https://connectapi.garmin.com/activitylist-service/activities/search/activities",
             {"start": "0", "limit": "1"}, {"Authorization": f"Bearer {jwt_web}"}),
        ]

    for label, url, params, extra_headers in endpoints:
        try:
            r = session.get(url, params=params, timeout=15, headers=extra_headers if extra_headers else None)
            ct = r.headers.get("Content-Type", "")
            if r.status_code == 200 and "text/html" not in ct:
                try:
                    data = r.json()
                    keys = list(data.keys())[:3] if isinstance(data, dict) else type(data).__name__
                    print(f"  ✓ {label}: JSON OK {keys}")
                    return True
                except Exception:
                    print(f"  ✗ {label}: 200 だが JSON パース失敗")
            else:
                print(f"  ✗ {label}: status={r.status_code} ct={ct[:40]}")
        except Exception as e:
            print(f"  ✗ {label}: {e}")

    return False


def main():
    print("=" * 60)
    print("  Garmin Cookie 取得 (Direct Playwright Login + SSO fallback)")
    print("=" * 60)

    # 戦略1: Playwright で直接ブラウザログイン（最も確実）
    print("\n[Strategy 1] Direct browser login via Playwright...")
    merged = get_jwt_via_browser_login()
    print(f"  取得クッキー: {list(merged.keys())}")

    if "JWT_WEB" not in merged:
        # 戦略2: cloudscraper で SSO チケット取得 → Playwright でチケット処理（フォールバック）
        print("\n[Strategy 2] SSO ticket + Playwright (fallback)...")
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

        if ticket_url:
            print(f"\nTicket URL: {ticket_url[:100]}")
            pw_cookies = get_jwt_via_playwright(ticket_url, sso_cookies)
            merged = {**sso_cookies, **pw_cookies}
            print(f"  取得クッキー: {list(merged.keys())}")
        else:
            print("  ⚠ SSO チケット取得に失敗しました（戦略2 スキップ）")

    # API テスト
    print("\n[API テスト]")
    valid = test_cookies(merged)

    # ファイルに保存
    cookie_str = "; ".join(f"{k}={v}" for k, v in merged.items())
    with open(SESSION_COOKIE_FILE, "w") as f:
        f.write(cookie_str)

    print(f"\n✓ {len(merged)}個のクッキーを {SESSION_COOKIE_FILE} に保存")
    print(f"  JWT_WEB: {'あり' if 'JWT_WEB' in merged else 'なし'}")

    if "JWT_WEB" not in merged:
        print("❌ JWT_WEB が取得できませんでした")
        sys.exit(1)

    if not valid:
        print("⚠ API テスト失敗（JWT_WEB はあり。メインスクリプトで再テスト）")
        # JWT_WEB があればメインスクリプトに任せる（exit 0）

    print("✓ 完了")


if __name__ == "__main__":
    main()
