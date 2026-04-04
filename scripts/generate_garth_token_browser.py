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


def save_garth_tokens(garth_dump: dict) -> None:
    """garth 互換形式でトークンを ~/.garth に保存する。"""
    os.makedirs(TOKEN_DIR, exist_ok=True)

    # garth は oauth1_token と oauth2_token を別ファイルで保存する
    oauth1_path = os.path.join(TOKEN_DIR, "oauth1_token.json")
    oauth2_path = os.path.join(TOKEN_DIR, "oauth2_token.json")

    with open(oauth1_path, "w") as f:
        json.dump(garth_dump["oauth1_token"], f, indent=2)

    with open(oauth2_path, "w") as f:
        json.dump(garth_dump["oauth2_token"], f, indent=2)

    print(f"✓ トークンを {TOKEN_DIR} に保存しました")


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
            """API リクエストの Authorization ヘッダーからJWTをキャプチャ（access_token のみ）。"""
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
                print(f"✓ access_token を取得しました（refresh_token も待機中）")

        def on_response(response):
            """OAuth exchange レスポンスから refresh_token をキャプチャ。"""
            if captured.get("refresh_token"):
                return
            if response.status != 200:
                return
            if "garmin.com" not in response.url:
                return
            try:
                body = response.json()
                if "access_token" not in body:
                    return
                rt = body.get("refresh_token", "")
                if rt:
                    captured["refresh_token"] = rt
                    print(f"✓ refresh_token を取得しました！")
                if not captured.get("access_token"):
                    captured["access_token"] = body["access_token"]
                    captured["payload"] = decode_jwt_payload(body["access_token"])
                    print(f"✓ access_token を取得しました！")
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

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
    refresh_token = captured.get("refresh_token", "")
    if refresh_token:
        rt_payload = decode_jwt_payload(refresh_token)
        rt_exp = rt_payload.get("exp", now_ts + 90 * 24 * 3600)
    else:
        rt_exp = now_ts + 90 * 24 * 3600
    refresh_expires_in = max(int(rt_exp - now_ts), 0)

    # garth 形式のトークン文字列を構築
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

    # garth.dumps() 互換: base64( json([oauth1, oauth2]) )
    garth_dump = base64.b64encode(json.dumps([oauth1, oauth2]).encode()).decode()

    # ~/.garth にトークンを保存（メインスクリプトが即座に使用可能に）
    save_garth_tokens(garth_data)

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
    print("✓ トークンは ~/.garth にも保存済みです。")
    print("  メインスクリプトを実行すればキャッシュから認証されます:")
    print("  python src/ガーミン活動データ取得.py")
    if captured.get("refresh_token"):
        print()
        print("✅ refresh_token も取得できました。garth が自動更新するため再ログイン不要です。")
    else:
        print()
        print("⚠ refresh_token を取得できませんでした。access_token のみ保存されています。")
        if exp:
            print(f"  このトークンは {local_exp} に期限切れになります。")
            print("  期限切れ後は再度このスクリプトを実行してください。")


if __name__ == "__main__":
    main()
