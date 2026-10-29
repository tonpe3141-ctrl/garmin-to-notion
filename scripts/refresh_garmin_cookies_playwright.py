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
import datetime
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
    if r.status_code >= 400:
        # Cloudflare に止められたのか Garmin に断られたのかを見分ける手がかり
        print(f"      title={_page_title(r.text)!r}")

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


def _page_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    return m.group(1).strip()[:60] if m else ""


# Connect のサービス URL。Garmin は何度か変えている（2026-05 は /modern、その後 /app）。
CONNECT_SERVICES = [f"{CONNECT_BASE}/app", f"{CONNECT_BASE}/modern/", f"{CONNECT_BASE}/modern"]


def _ticket_from_sso_session(s):
    """ログイン済みの SSO セッション (CASTGC) で、Connect 用のサービスチケットを発行させる。

    CAS の普通の使い方で、パスワードは送らない。2026-10-28 から /app 向けのパスワードログインが 403 になったが、
    embed 向けのログインは通る。そのセッションから Connect 用のチケットを取る。
    サービス URL とエンドポイントの組み合わせを順に試し、どれが通ったかをログに残す。
    """
    print("[SSO-3] SSO セッションから Connect 用のチケットを取得...")
    for svc in CONNECT_SERVICES:
        for path, params in (
            ("login", {"service": svc}),
            ("signin", {"service": svc, "webhost": CONNECT_BASE, "gauthHost": SSO_BASE,
                        "clientId": "GarminConnect", "consumeServiceTicket": "false"}),
        ):
            label = f"/sso/{path} service={svc.replace(CONNECT_BASE, '')}"
            try:
                r = s.get(f"{SSO_BASE}/{path}", params=params, timeout=20, allow_redirects=False)
            except Exception as e:
                print(f"      {label}: {e}")
                continue
            loc = r.headers.get("Location", "")
            m = re.search(r"ticket=(ST-[A-Za-z0-9\-_]+)", loc + " " + r.text)
            if m:
                print(f"      ✓ {label}: status={r.status_code} チケットあり")
                return loc if "ticket=" in loc else f"{svc}?ticket={m.group(1)}"
            print(f"      {label}: status={r.status_code} チケットなし"
                  f" location={loc.split('?')[0][:70]!r} title={_page_title(r.text)!r}")
            time.sleep(1)
    return None


def _cookie_list(s) -> list:
    """requests のクッキーを、ドメインとパスを保ったまま Playwright に渡せる形にする。"""
    return [
        {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/", "secure": bool(c.secure)}
        for c in s.cookies
    ]


def get_sso_ticket() -> tuple:
    """
    旧 SSO でパスワードログインし、(sso_cookies, ticket_url, cookie_list) を返す。

    パスワードを送るのは原則1回（/app が断られたときだけ embed でもう1回）。
      1. /app サービス向けにログイン → そのままチケットが出れば使う
      2. 断られたら embed（garth と同じ）でログインし、そのセッションから Connect 用のチケットを取る
    チケットが取れなくても、ログイン済みのクッキーはブラウザ側（get_jwt_via_playwright）で使う。
    """
    s = _make_session()
    sso_cookies, ticket_url = _do_sso_login(s, SIGNIN_PARAMS)

    if not ticket_url:
        print("      → /app SSO 失敗。embed フローで再試行...")
        s = _make_session()
        sso_cookies, embed_ticket = _do_sso_login(s, SIGNIN_PARAMS_EMBED)
        if not embed_ticket and "CASTGC" not in sso_cookies:
            raise RuntimeError("SSO ログインに失敗しました")
        # embed のチケットは sso/embed 向けで、Connect のセッションは作れない
        ticket_url = _ticket_from_sso_session(s)
        sso_cookies = {c["name"]: c["value"] for c in _cookie_list(s)}

    return sso_cookies, ticket_url, _cookie_list(s)


EMAIL_SELECTOR = (
    'input[name="username"], input#username, input[type="email"], '
    'input[name="email"], input#email'
)
PASSWORD_SELECTOR = 'input[type="password"]'
SUBMIT_SELECTOR = (
    'button[type="submit"], input[type="submit"], '
    '#login-btn-signin, a#login-btn-signin'
)


def _find_visible(page, selector: str, timeout_s: float):
    """全フレームから selector に合う表示中の要素を探す。見つかるまで timeout_s 秒待つ。

    新ポータル (sso.garmin.com/portal/...) は JS で描画されるので、
    domcontentloaded 直後にはフォームがまだ無い（2026-10 まで毎回 email field not found）。
    旧ウィジェットは iframe 内なので、フレームも順に見る。
    """
    deadline = time.time() + timeout_s
    while True:
        for frame in page.frames:
            try:
                for el in frame.query_selector_all(selector):
                    if el.is_visible():
                        return frame, el
            except Exception:
                pass
        if time.time() >= deadline:
            return None, None
        time.sleep(0.5)


def _describe_login_page(page):
    """フォームが見つからないときの手がかり（入力欄・ボタンの種類だけ。値は出さない）。"""
    try:
        print(f"      title={page.title()!r} | URL: {page.url[:90]}")
        for frame in page.frames:
            inputs = frame.query_selector_all("input")
            buttons = frame.query_selector_all("button")
            desc = [
                f"{i.get_attribute('type')}:{i.get_attribute('name') or i.get_attribute('id')}"
                for i in inputs[:10]
            ]
            labels = [(b.inner_text() or "").strip()[:20] for b in buttons[:6]]
            print(f"      frame {frame.url[:60]} inputs={desc} buttons={labels}")
        page.screenshot(path="/tmp/garmin_pw_debug.png")
        print("      スクリーンショット: /tmp/garmin_pw_debug.png")
    except Exception as e:
        print(f"      (ページ情報の取得に失敗: {e})")


def _submit(frame, field):
    for el in frame.query_selector_all(SUBMIT_SELECTOR):
        try:
            if el.is_visible() and el.is_enabled():
                el.click(timeout=5000)
                print("      submit clicked")
                return
        except Exception:
            pass
    field.press("Enter")
    print("      submit: pressed Enter")


def fill_login_form(page, wait_s: float = 30) -> bool:
    """SSO ログインフォームにメール/パスワードを入れて送信する。送信できたら True。

    メールとパスワードが同じ画面にある形と、メール → 次へ → パスワード の2段階の両方に対応する。
    """
    frame, email = _find_visible(page, EMAIL_SELECTOR, wait_s)
    if not email:
        print("      ⚠ email field not found")
        _describe_login_page(page)
        return False
    email.fill(EMAIL)
    print("      email filled")

    pw_frame, pw = _find_visible(page, PASSWORD_SELECTOR, 0)
    if not pw:
        # 2段階のログイン: 先にメールを送ってからパスワード欄を待つ
        _submit(frame, email)
        pw_frame, pw = _find_visible(page, PASSWORD_SELECTOR, 15)
        if not pw:
            print("      ⚠ password field not found")
            _describe_login_page(page)
            return False
    frame = pw_frame
    pw.fill(PASSWORD)
    print("      password filled")
    time.sleep(0.5)  # フォーム入力後の短い待機
    _submit(frame, pw)
    return True


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
            submitted = fill_login_form(page)
            if not submitted:
                print("      ⚠ フォーム入力失敗。ログインをスキップします。")

            # Step 3: JWT_WEB が設定されるまで最大 40 秒待機（送信できなかったときは待たない）
            # URLがSSO sign-inページのまま変化しない場合は早期終了（ログイン失敗）
            print("[PW-D4] Waiting for JWT_WEB (up to 40s)...")
            signin_url_prefix = "sso.garmin.com"
            for i in range(40 if submitted else 0):
                cookies_now = context.cookies(["https://connect.garmin.com"])
                if any(c["name"] == "JWT_WEB" for c in cookies_now):
                    print(f"      ✓ JWT_WEB 取得成功 ({i}s) | URL: {page.url[:60]}")
                    jwt_found = True
                    break
                # SSO ページに留まっている場合は 25 秒後に早期終了
                if i == 25 and signin_url_prefix in page.url:
                    print(f"      ⚠ SSO ページのまま変化なし → Strategy 1 早期終了")
                    break
                if i % 10 == 0:
                    print(f"      waiting {i}s | URL: {page.url[:70]}")
                time.sleep(1)

            if not jwt_found:
                print(f"      ⚠ JWT_WEB が取得できませんでした | URL: {page.url}")
                _describe_login_page(page)
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


def _wait_for_jwt(context, page, seconds: int) -> bool:
    for i in range(seconds):
        if any(c["name"] == "JWT_WEB" for c in context.cookies([CONNECT_BASE])):
            print(f"      ✓ JWT_WEB 取得成功 ({i}s) | URL: {page.url[:70]}")
            return True
        if i % 5 == 0:
            print(f"      waiting {i}s | URL: {page.url[:70]}")
        time.sleep(1)
    return False


def get_jwt_via_playwright(ticket_url, sso_cookies: dict, cookie_list: list = None) -> dict:
    """
    SSO でログインしたクッキーを持ったブラウザで Connect に入り、connect.garmin.com の JS に
    JWT_WEB をセットさせて回収する。

    戦略:
      1. チケット URL（/app?ticket=... など）があれば移動
      2. だめなら CAS のログイン URL → /app/home の順に移動（SSO セッションでチケットが出る）
      3. 新しいサインイン画面に着き、フォームが出ていれば入力する
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ❌ Playwright 未インストール")
        return {}

    print(f"[PW-1] Navigate: {(ticket_url or '(チケットなし)')[:80]}")

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

        # SSO クッキーを、requests が受け取ったときのドメインとパスのまま渡す。
        # 以前は全ドメイン・パス "/" にばらまいていたため、同名のクッキーが重なって SSO が
        # ログイン済みと認識しないことがあった。
        if cookie_list:
            for c in cookie_list:
                try:
                    context.add_cookies([c])
                except Exception as e:
                    print(f"      ⚠ クッキー {c['name']} を渡せませんでした: {e}")
        else:
            for name, value in sso_cookies.items():
                try:
                    context.add_cookies([{"name": name, "value": value, "domain": ".garmin.com", "path": "/"}])
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

        # Phase 1: チケット URL で JWT_WEB を待機（最大15秒）
        jwt_found = False
        if ticket_url:
            try:
                page.goto(ticket_url, wait_until="networkidle", timeout=45000)
            except Exception as e:
                print(f"      goto warning (continuing): {e}")
            print(f"      URL after nav: {page.url}")
            print("[PW-2] Phase 1: Waiting for JWT_WEB at ticket URL (15s)...")
            jwt_found = _wait_for_jwt(context, page, 15)

        # Phase 2: JWT_WEB がなければ、ブラウザ側でも SSO セッションから入る。
        #   a. CAS のログイン URL（ログイン済みならチケット付きで Connect に戻される）
        #   b. /app/home（新アプリ経由。SSO が自動でチケットを出すことがある）
        for label, url in (("CAS", f"{SSO_BASE}/login?service={CONNECT_BASE}/app"),
                           ("app/home", f"{CONNECT_BASE}/app/home")):
            if jwt_found:
                break
            print(f"[PW-3] Phase 2 ({label}): {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                print(f"      goto warning (continuing): {e}")
            jwt_found = _wait_for_jwt(context, page, 20)

        # Phase 3: 新しいサインイン画面に着いていて、フォームが出ていれば入力する。
        # Cloudflare の人間確認がブラウザ自身で通ったときだけ（突破はしない）。
        if not jwt_found and "sso.garmin.com/portal" in page.url:
            print("[PW-4] Phase 3: 新しいサインイン画面でログイン...")
            if fill_login_form(page, wait_s=20):
                jwt_found = _wait_for_jwt(context, page, 40)

        if not jwt_found:
            print(f"      ⚠ JWT_WEB が取得できませんでした | URL: {page.url}")
            _describe_login_page(page)

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


def prefetch_garmin_data(page, activities_limit: int = None) -> bool:
    if activities_limit is None:
        activities_limit = int(os.environ.get("GARMIN_ACTIVITIES_FETCH_LIMIT", "200"))
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
    seen_ids: set = set()

    # ⚠ 下のページネーションで page.evaluate から呼ぶ fetch のレスポンスも page.on("response") に届く。
    #   以前はそれを素通しで extend していたため、同じ50件が2回入り、次の start も倍に進んで
    #   その先の50件が丸ごと抜けていた（2026-08〜10 のドキュメントの週次サマリーが実際の2倍になっていた）。
    #   activityId で重複を落とし、件数（＝次の start）は重複を除いた数で数える。
    def _add_activities(items) -> int:
        added = 0
        for a in items:
            aid = a.get("activityId") if isinstance(a, dict) else None
            if aid is None or aid in seen_ids:
                continue
            seen_ids.add(aid)
            intercepted_activities.append(a)
            added += 1
        return added

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
                        added = _add_activities(data)
                        if added:
                            print(f"  ✓ intercepted: +{added} (total {len(intercepted_activities)})")
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
                # レスポンスの捕捉側で先に入っていることもあるので、増えた数は件数の差で見る
                _add_activities(result)
                grew = len(intercepted_activities) - start
                print(f"  ✓ ページネーション: start={start} +{grew} (total {len(intercepted_activities)})")
                if len(result) < 50:
                    break
                if grew == 0:
                    # 同じページしか返ってこない（start が効いていない）。無限ループを避ける
                    print("  ⚠ 新しい活動が増えないのでページネーションを打ち切る")
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

    # 上限を超えた分は保存しないので、ラップも取りにいかない
    del intercepted_activities[activities_limit:]

    # ── ランニング活動のスプリット（ラップ）を取得 ───────────────────────────────
    # GarminPreloadedClient はラップが必須。ブラウザの SPA ヘッダーで直接 fetch する。
    if spa_request_headers and intercepted_activities:
        running_ids = [
            str(a.get("activityId"))
            for a in intercepted_activities
            if a.get("activityId") and isinstance(a.get("activityType"), dict) and
            "run" in (a["activityType"].get("typeKey") or "").lower()
        ]
        print(f"  → ランニング {len(running_ids)} 件のスプリット(ラップ)を取得中...")
        headers_js_splits = json.dumps(spa_request_headers)

        # 20件ずつバッチ処理（サーバー負荷を抑えつつ高速化）
        # /splits → /typedsplits の順に試す（新旧APIどちらかが返せばOK）
        BATCH_SIZE = 20
        for batch_start in range(0, len(running_ids), BATCH_SIZE):
            batch_ids = running_ids[batch_start:batch_start + BATCH_SIZE]
            ids_js = json.dumps(batch_ids)
            try:
                batch_results = page.evaluate(f"""
                    async () => {{
                        const ids = {ids_js};
                        const headers = {headers_js_splits};
                        const out = [];
                        for (const id of ids) {{
                            try {{
                                // /splits を優先し、失敗時は /typedsplits を試す
                                let data = null;
                                for (const ep of ['/splits', '/typedsplits']) {{
                                    const r = await fetch(
                                        `/gc-api/activity-service/activity/${{id}}${{ep}}`,
                                        {{credentials:'include', headers}}
                                    );
                                    if (r.ok) {{
                                        const d = await r.json();
                                        if (d) {{ data = d; break; }}
                                    }}
                                }}
                                if (data) out.push({{id, data}});
                            }} catch(e) {{}}
                        }}
                        return out;
                    }}
                """)
                for item in (batch_results or []):
                    if item.get("data"):
                        intercepted_splits[item["id"]] = item["data"]
            except Exception as e:
                print(f"  ⚠ スプリットバッチ取得エラー (start={batch_start}): {e}")
        print(f"  ✓ {len(intercepted_splits)} 件のスプリット取得完了")
    else:
        print("  ⚠ SPA ヘッダー未取得のためスプリットをスキップ")

    # ── 日次健康データ（睡眠・HRV・ボディバッテリー等）を取得 ──────────────
    health_data: dict = {}
    race_predictions: dict = {}
    if spa_request_headers:
        health_data, race_predictions = prefetch_health_data(page, spa_request_headers)
    else:
        print("  ⚠ SPA ヘッダー未取得のため健康データをスキップ")

    print(f"  → 合計: {len(intercepted_activities)} activities, "
          f"{len(intercepted_splits)} splits, {len(health_data)} 日分の健康データ")

    if not intercepted_activities:
        print("  ✗ アクティビティデータが取得できませんでした")
        return False

    prefetch = {
        "activities": intercepted_activities[:activities_limit],
        "splits": intercepted_splits,
        "details": {},
        "health": health_data,
        "race_predictions": race_predictions,
    }
    try:
        with open("/tmp/garmin_prefetch.json", "w") as pf:
            json.dump(prefetch, pf)
        print(f"  ✓ /tmp/garmin_prefetch.json に保存 ({len(prefetch['activities'])} activities)")
        return True
    except Exception as e:
        print(f"  ✗ 保存失敗: {e}")
        return False


def prefetch_health_data(page, spa_headers: dict, days: int = None) -> tuple:
    """
    直近 days 日分の日次健康データとレース予測をブラウザ経由で取得する。
    日数は本体スクリプトの GARMIN_HEALTH_FETCH_DAYS と揃える（前週比の算出に2週間必要）。

    Python の requests では /gc-api/ が 403 になる環境でも、
    SPA と同じヘッダー + Cookie でブラウザ内から fetch すれば取得できる。

    返り値: ({"YYYY-MM-DD": {種別: レスポンス}}, レース予測 dict)
    """
    if days is None:
        days = int(os.environ.get("GARMIN_HEALTH_FETCH_DAYS", "14"))
    print("\n[健康データ事前取得] 直近 %d 日分を取得中..." % days)

    # 日付は必ず JST で数える。ランナーの TZ（以前は America/Montreal）で数えると
    # 8:30 JST の実行時に「今日」が前日になり、当日朝の睡眠・HRV・準備度が毎日欠けていた。
    today = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).date()
    dates = [(today - datetime.timedelta(days=i)).isoformat() for i in range(days)]
    headers_js = json.dumps(spa_headers)
    dates_js = json.dumps(dates)

    # display_name（睡眠・RHR・レース予測に必要）をブラウザから取得
    display_name = ""
    try:
        display_name = page.evaluate(f"""
            async () => {{
                const headers = {headers_js};
                const paths = [
                    '/gc-api/userprofile-service/socialProfile',
                    '/gc-api/userprofile-service/userprofile/user-settings/',
                    '/gc-api/userprofile-service/userprofile/personal-information/'
                ];
                for (const p of paths) {{
                    try {{
                        const r = await fetch(p, {{credentials:'include', headers}});
                        if (!r.ok) continue;
                        const d = await r.json();
                        const name = d.displayName
                            || (d.userData && d.userData.displayName)
                            || (d.userInfo && d.userInfo.displayName);
                        if (name) return name;
                    }} catch(e) {{}}
                }}
                return '';
            }}
        """) or ""
    except Exception as e:
        print(f"  ⚠ displayName 取得エラー: {e}")
    if display_name:
        print(f"  ℹ displayName: {display_name}")
    else:
        print("  ⚠ displayName 取得失敗（睡眠・安静時心拍・レース予測はスキップされます）")

    name_js = json.dumps(display_name)

    try:
        result = page.evaluate(f"""
            async () => {{
                const headers = {headers_js};
                const dates = {dates_js};
                const name = {name_js};
                const B = '/gc-api';

                const get = async (path) => {{
                    try {{
                        const r = await fetch(path, {{credentials:'include', headers}});
                        if (!r.ok) return null;
                        return await r.json();
                    }} catch(e) {{ return null; }}
                }};

                const health = {{}};
                for (const d of dates) {{
                    const day = {{}};
                    day.hrv = await get(`${{B}}/hrv-service/hrv/${{d}}`);
                    day.steps = await get(`${{B}}/usersummary-service/stats/steps/daily/${{d}}/${{d}}`);
                    day.body_battery = await get(
                        `${{B}}/wellness-service/wellness/bodyBattery/reports/daily?startDate=${{d}}&endDate=${{d}}`);
                    day.stress = await get(`${{B}}/wellness-service/wellness/dailyStress/${{d}}`);
                    day.training_readiness = await get(
                        `${{B}}/metrics-service/metrics/trainingreadiness/${{d}}`);
                    day.max_metrics = await get(
                        `${{B}}/metrics-service/metrics/maxmet/daily/${{d}}/${{d}}`);
                    day.training_status = await get(
                        `${{B}}/metrics-service/metrics/trainingstatus/aggregated/${{d}}`);
                    day.spo2 = await get(`${{B}}/wellness-service/wellness/daily/spo2/${{d}}`);
                    day.respiration = await get(
                        `${{B}}/wellness-service/wellness/daily/respiration/${{d}}`);
                    if (name) {{
                        day.sleep = await get(
                            `${{B}}/wellness-service/wellness/dailySleepData/${{name}}`
                            + `?date=${{d}}&nonSleepBufferMinutes=60`);
                        day.rhr = await get(
                            `${{B}}/userstats-service/wellness/daily/${{name}}`
                            + `?fromDate=${{d}}&untilDate=${{d}}&metricId=60`);
                    }}
                    // null（取得失敗）のキーは保存しない → Python 側でフォールバックさせる
                    for (const k of Object.keys(day)) {{
                        if (day[k] === null || day[k] === undefined) delete day[k];
                    }}
                    health[d] = day;
                }}

                let race = null;
                if (name) {{
                    race = await get(
                        `${{B}}/metrics-service/metrics/racepredictions/latest/${{name}}`);
                }}
                return {{health, race: race || {{}}}};
            }}
        """)
    except Exception as e:
        print(f"  ✗ 健康データ取得エラー: {e}")
        return {}, {}

    health = (result or {}).get("health") or {}
    race = (result or {}).get("race") or {}

    for d in dates:
        got = sorted((health.get(d) or {}).keys())
        print(f"  {d}: {len(got)} 種別 {got if got else '（取得できず）'}")
    if race:
        print(f"  ✓ レース予測: {race.get('time5K')}s(5K) / {race.get('timeMarathon')}s(Full)")
    else:
        print("  ⚠ レース予測は取得できませんでした")

    return health, race


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
        # パスワードを何度も送るとログイン制限が厳しくなるので、再試行は通信エラーのときに1回だけ
        sso_cookies, ticket_url, cookie_list = {}, None, []
        for attempt in range(2):
            try:
                sso_cookies, ticket_url, cookie_list = get_sso_ticket()
                break
            except Exception as e:
                print(f"  SSO 試行 {attempt+1} 失敗: {e}")
                if attempt == 0:
                    print("  30s 待機して再試行...")
                    time.sleep(30)

        if ticket_url or "CASTGC" in sso_cookies:
            print(f"\nTicket URL: {(ticket_url or '(なし。SSO セッションで入る)')[:100]}")
            pw_cookies = get_jwt_via_playwright(ticket_url, sso_cookies, cookie_list)
            merged = {**sso_cookies, **pw_cookies}
            print(f"  取得クッキー: {list(merged.keys())}")
        else:
            print("  ⚠ SSO ログインに失敗しました（戦略2 スキップ）")

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
