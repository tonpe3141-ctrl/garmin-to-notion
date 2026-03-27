"""
ブラウザ経由でGarminトークンを取得する代替スクリプト。

API の SSO エンドポイントがレートリミットされている場合でも、
ブラウザのログインフローは別エンドポイントを使うため動作する。

使い方:
  pip3 install playwright
  python3 -m playwright install chromium
  python3 scripts/generate_garth_token_browser.py
"""
import base64
import json
import sys
import time
from datetime import datetime, timezone


def decode_jwt_payload(token: str) -> dict:
    """JWT の payload 部分をデコードして返す。"""
    try:
        part = token.split(".")[1]
        part += "=" * (4 - len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright が必要です。以下を実行してください:")
        print("  pip3 install playwright")
        print("  python3 -m playwright install chromium")
        sys.exit(1)

    print("=" * 60)
    print("ブラウザが開きます。Garmin Connect にログインしてください。")
    print("ログイン完了後、自動的にトークンが取得されます。")
    print("=" * 60)
    print()

    captured: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        def on_request(request):
            """API リクエストの Authorization ヘッダーからJWTをキャプチャ。"""
            if captured.get("access_token"):
                return
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer "):
                return
            token = auth[7:]
            if len(token) < 100:  # 短すぎるトークンはスキップ
                return
            payload = decode_jwt_payload(token)
            # Garmin の JWT には sub または jti フィールドがある
            if "sub" in payload or "jti" in payload:
                captured["access_token"] = token
                captured["payload"] = payload
                print(f"✓ トークンを取得しました！")

        page.on("request", on_request)

        # Garmin Connect のログインページへ遷移
        page.goto("https://connect.garmin.com/signin/")
        print("→ ブラウザでメールアドレスとパスワードを入力してログインしてください。")
        print("  （MFA が表示された場合もブラウザで対応してください）")
        print()

        # トークンが取得されるかブラウザが閉じられるまで待機
        timeout = 180  # 3分
        for _ in range(timeout):
            if captured.get("access_token"):
                break
            try:
                if not browser.is_connected():
                    break
            except Exception:
                break
            time.sleep(1)

        if browser.is_connected():
            browser.close()

    access_token = captured.get("access_token")
    if not access_token:
        print("❌ トークンを取得できませんでした。")
        print("   ブラウザが閉じられる前にログインが完了しませんでした。")
        sys.exit(1)

    payload = captured.get("payload", {})

    # JWT の有効期限を確認
    exp = payload.get("exp")
    if exp:
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        expires_in = max(int((expires_at - datetime.now(timezone.utc)).total_seconds()), 3600)
        local_exp = expires_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
        print(f"  トークン有効期限: {local_exp}")
    else:
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        expires_in = 3600

    # garth 形式のトークン文字列を構築
    garth_dump = json.dumps({
        "oauth1_token": {
            "oauth_token": "",
            "oauth_token_secret": "",
            "mfa_token": None,
            "mfa_expiration_timestamp": None,
            "domain": "garmin.com",
        },
        "oauth2_token": {
            "scope": payload.get("scope", ""),
            "jti": payload.get("jti", ""),
            "token_type": "Bearer",
            "access_token": access_token,
            "refresh_token": "",
            "expires_in": expires_in,
            "expires_at": expires_at.isoformat(),
        },
    })

    print()
    print("=" * 60)
    print("GARTH_TOKENS_B64 の値（GitHub Secrets に設定してください）:")
    print("=" * 60)
    print(garth_dump)
    print("=" * 60)
    print()
    print("設定方法:")
    print("  GitHub > Settings > Secrets and variables > Actions")
    print("  GARTH_TOKENS_B64 の値を上記で上書きしてください。")
    print()
    if exp:
        print(f"⚠ このトークンは {local_exp} に期限切れになります。")
        print("  期限切れ前にスクリプトを再実行してトークンを更新してください。")


if __name__ == "__main__":
    main()
