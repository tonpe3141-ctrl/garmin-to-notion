"""
Garmin Connect ログイン回復スクリプト。

【背景】
Garmin の SSO がプログラムによるログインをブロックしている場合、
通常のブラウザからもログインできなくなることがあります。
このスクリプトは以下の方法で問題を回避します:

1. ネットワーク切り替え案内（IP変更でブロック解除）
2. Playwright ステルスモードで「本物のブラウザ」セッションを作成
3. ユーザーが手動でログイン
4. ログイン成功後、JWT トークンを自動キャプチャ
5. ~/.garth に保存してメインスクリプトで使用可能に

【前提】
  pip3 install playwright
  python3 -m playwright install chromium

【使い方】
  python3 scripts/recover_garmin_login.py
"""
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone


TOKEN_DIR = os.path.expanduser("~/.garth")


def decode_jwt_payload(token: str) -> dict:
    """JWT の payload 部分をデコードして返す。"""
    try:
        part = token.split(".")[1]
        part += "=" * (4 - len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def save_garth_tokens(garth_data: dict) -> None:
    """garth 互換形式でトークンを ~/.garth に保存する。"""
    os.makedirs(TOKEN_DIR, exist_ok=True)
    oauth1_path = os.path.join(TOKEN_DIR, "oauth1_token.json")
    oauth2_path = os.path.join(TOKEN_DIR, "oauth2_token.json")

    with open(oauth1_path, "w") as f:
        json.dump(garth_data["oauth1_token"], f, indent=2)
    with open(oauth2_path, "w") as f:
        json.dump(garth_data["oauth2_token"], f, indent=2)
    print(f"  ✓ トークンを {TOKEN_DIR} に保存しました")


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright が必要です。以下を実行してください:")
        print("  pip3 install playwright")
        print("  python3 -m playwright install chromium")
        sys.exit(1)

    print()
    print("=" * 60)
    print("  Garmin Connect ログイン回復ツール")
    print("=" * 60)
    print()
    print("⚠ 重要: ログイン前にネットワークを切り替えてください！")
    print()
    print("  現在のIPがGarminにブロックされている可能性があります。")
    print("  以下のいずれかを行ってからEnterを押してください:")
    print()
    print("  方法1: スマホのテザリング（モバイルデータ）に切り替え")
    print("         → Wi-Fi を OFF → iPhone テザリングを ON")
    print()
    print("  方法2: VPN を使用（無料VPNでもOK）")
    print("         → ProtonVPN / Windscribe など")
    print()
    print("  方法3: 別のWi-Fiネットワークに接続")
    print()

    input("  ネットワーク切り替え後、Enter を押してください...")

    print()
    print("ブラウザを起動します...")
    print("→ ブラウザで Garmin Connect にログインしてください")
    print("→ ログイン完了後、トークンを自動取得します")
    print()

    captured: dict = {}

    with sync_playwright() as p:
        # ステルスモード: 自動化検出を回避するための設定
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )

        # リアルなブラウザコンテキストを作成
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )

        # webdriver フラグを隠す
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            // Chrome プラグイン配列を模造
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            // 言語を設定
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ja', 'en-US', 'en']
            });
        """)

        page = context.new_page()

        def on_request(request):
            """API リクエストの Authorization ヘッダーからJWTをキャプチャ。"""
            if captured.get("access_token"):
                return
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer "):
                return
            token = auth[7:]
            if len(token) < 100:
                return
            payload = decode_jwt_payload(token)
            if "sub" in payload or "jti" in payload:
                captured["access_token"] = token
                captured["payload"] = payload
                print()
                print("  ✅ トークンを取得しました！")

        def on_response(response):
            """OAuth トークンレスポンスをキャプチャ。"""
            # refresh_token が取れたら完了（access_token だけでは不十分）
            if captured.get("refresh_token"):
                return
            url = response.url
            if response.status != 200:
                return
            # connectapi.garmin.com の全レスポンスを監視して access_token/refresh_token を拾う
            # 以前のフィルタ: "oauth" in url AND "token" in url
            # → exchange エンドポイント (oauth/exchange/user/2.0) は "token" を含まないためスルーされていた
            if "garmin.com" not in url:
                return
            try:
                body = response.json()
                if "access_token" not in body:
                    return
                rt = body.get("refresh_token", "")
                at = body["access_token"]
                if rt:
                    captured["refresh_token"] = rt
                    print()
                    print(f"  ✅ refresh_token を取得しました！（URL: {url[:80]}）")
                if not captured.get("access_token"):
                    captured["access_token"] = at
                    captured["payload"] = decode_jwt_payload(at)
                    print()
                    print(f"  ✅ access_token を取得しました！")
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        # Garmin のログインページに遷移
        try:
            page.goto(
                "https://sso.garmin.com/portal/sso/en-US/sign-in"
                "?clientId=GarminConnect"
                "&service=https%3A%2F%2Fconnect.garmin.com%2Fapp",
                timeout=30000,
            )
        except Exception as e:
            print(f"  ⚠ ページ読み込みエラー: {e}")
            print("  ブラウザで手動でログインしてください。")

        print("  → ブラウザでメールアドレスとパスワードを入力してください")
        print("  → MFA が表示された場合もブラウザで対応してください")
        print("  → ログイン完了まで最大5分待機します")
        print()

        # トークンが取得されるまで最大5分待機
        timeout = 300
        dot_count = 0
        for i in range(timeout):
            if captured.get("access_token"):
                break
            try:
                if not browser.is_connected():
                    break
            except Exception:
                break
            time.sleep(1)
            dot_count += 1
            if dot_count % 10 == 0:
                elapsed = dot_count
                remain = timeout - elapsed
                print(f"  ⏳ 待機中... ({elapsed}秒経過, 残り{remain}秒)")

        if browser.is_connected():
            # ログイン成功後、少し待ってからブラウザを閉じる
            if captured.get("access_token"):
                time.sleep(2)
            browser.close()

    access_token = captured.get("access_token")
    if not access_token:
        print()
        print("=" * 60)
        print("❌ トークンを取得できませんでした。")
        print()
        print("考えられる原因:")
        print("  1. ログインが完了しなかった")
        print("  2. ネットワークがまだブロックされている")
        print("     → 別のネットワーク（テザリング/VPN）を試してください")
        print("  3. Garmin アカウントに問題がある")
        print("     → https://www.garmin.com/account/ でパスワードリセット")
        print("=" * 60)
        sys.exit(1)

    payload = captured.get("payload", {})
    refresh_token = captured.get("refresh_token", "")

    # JWT の有効期限を確認
    import time as _time
    now_ts = int(_time.time())
    exp = payload.get("exp")
    if exp:
        expires_in = max(int(exp - now_ts), 3600)
        local_exp = datetime.fromtimestamp(exp, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
        print(f"  トークン有効期限: {local_exp}")
    else:
        exp = now_ts + 3600
        expires_in = 3600

    # refresh_token の有効期限（取得できた場合はJWTから、なければ90日）
    if refresh_token:
        rt_payload = decode_jwt_payload(refresh_token)
        rt_exp = rt_payload.get("exp", now_ts + 90 * 24 * 3600)
    else:
        rt_exp = now_ts + 90 * 24 * 3600
    refresh_expires_in = max(int(rt_exp - now_ts), 0)

    # garth 形式のトークンを構築
    oauth1 = {
        "oauth_token": "",
        "oauth_token_secret": "",
        "mfa_token": None,
        "mfa_expiration_timestamp": None,
        "domain": "garmin.com",
    }
    oauth2 = {
        "scope": payload.get("scope", ""),
        "jti": payload.get("jti", ""),
        "token_type": "Bearer",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "expires_at": exp,                      # int (Unix timestamp)
        "refresh_token_expires_in": refresh_expires_in,
        "refresh_token_expires_at": rt_exp,
    }
    garth_data = {"oauth1_token": oauth1, "oauth2_token": oauth2}

    # ~/.garth に保存
    save_garth_tokens(garth_data)

    # GitHub Secret 用の文字列も出力
    # garth.dumps() 互換: base64( json([oauth1, oauth2]) )
    garth_dump = base64.b64encode(json.dumps([oauth1, oauth2]).encode()).decode()
    print()
    print("=" * 60)
    print("✅ ログイン回復成功！")
    print("=" * 60)
    print()
    print(f"  トークンは {TOKEN_DIR} に保存されました。")
    print("  メインスクリプトを実行できます:")
    print()
    print("    python src/ガーミン活動データ取得.py")
    print()
    print("─" * 60)
    print("GitHub Secrets 用（任意）:")
    print("─" * 60)
    print(garth_dump)
    print("─" * 60)
    print()
    print("設定方法:")
    print("  GitHub > Settings > Secrets and variables > Actions")
    print("  GARTH_TOKENS_B64 の値を上記で上書きしてください。")
    if exp:
        print()
        print(f"  ⚠ トークン有効期限: {local_exp}")


if __name__ == "__main__":
    main()
