"""
Chrome の DevTools からコピーした JWT を GARTH_TOKENS_B64 形式に変換するスクリプト。

【手順】
1. Chrome で https://connect.garmin.com を開く（ログイン済みの状態）
2. DevTools を開く (Cmd + Option + I)
3. 「Application」タブ → Cookies → https://connect.garmin.com
4. 「JWT_WEB」の Value 欄の文字列を全選択してコピー
5. このスクリプトを実行して貼り付ける

使い方:
  python3 scripts/generate_garth_token_from_jwt.py
"""
import base64
import json
import sys
import time
from datetime import datetime, timedelta, timezone


def to_garth_b64(oauth1: dict, oauth2: dict) -> str:
    """garth.dumps() と同じ形式: base64( json([oauth1, oauth2]) )"""
    return base64.b64encode(json.dumps([oauth1, oauth2]).encode()).decode()


def decode_jwt_payload(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (4 - len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def main():
    print("=" * 60)
    print("ChromeのDevToolsからコピーしたJWTを貼り付けてください。")
    print("（Application → Cookies → JWT_WEB の Value）")
    print("=" * 60)

    jwt_token = input("JWT > ").strip()

    if jwt_token.lower().startswith("bearer "):
        jwt_token = jwt_token[7:].strip()

    if len(jwt_token) < 50 or jwt_token.count(".") < 2:
        print("❌ 有効なJWTではありません。JWT_WEB の Value 欄の値のみを貼り付けてください。")
        sys.exit(1)

    payload = decode_jwt_payload(jwt_token)
    if not payload:
        print("❌ JWTのデコードに失敗しました。")
        sys.exit(1)

    now_ts = int(time.time())
    exp = payload.get("exp")
    if exp:
        expires_in = max(int(exp - now_ts), 0)
        local_exp = datetime.fromtimestamp(exp, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
        if expires_in <= 0:
            print("❌ このJWTはすでに期限切れです。ページをリロードして JWT_WEB を再取得してください。")
            sys.exit(1)
        print(f"✓ JWTのデコード成功")
        print(f"  有効期限: {local_exp}（あと {expires_in // 3600}時間 {(expires_in % 3600) // 60}分）")
    else:
        exp = now_ts + 3600
        expires_in = 3600
        print("⚠ 有効期限が読み取れませんでした（1時間として設定）")

    # refresh_token は取得できないため90日後を仮設定
    refresh_expires_in = 90 * 24 * 3600
    refresh_expires_at = now_ts + refresh_expires_in

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
        "access_token": jwt_token,
        "refresh_token": "",
        "expires_in": expires_in,
        "expires_at": exp,                          # int (Unix timestamp)
        "refresh_token_expires_in": refresh_expires_in,
        "refresh_token_expires_at": refresh_expires_at,
    }

    garth_dump = to_garth_b64(oauth1, oauth2)

    print()
    print("=" * 60)
    print("GARTH_TOKENS_B64（GitHub Secrets に設定してください）:")
    print("=" * 60)
    print(garth_dump)
    print("=" * 60)
    print()
    print("設定方法:")
    print("  GitHub > Settings > Secrets and variables > Actions")
    print("  GARTH_TOKENS_B64 の値を上記で上書きしてください。")
    if exp:
        print()
        print(f"⚠ access_token の有効期限: {local_exp}")
        print("  期限切れ後は再度このスクリプトを実行してください。")


if __name__ == "__main__":
    main()
