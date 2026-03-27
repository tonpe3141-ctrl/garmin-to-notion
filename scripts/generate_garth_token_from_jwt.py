"""
Chrome の DevTools からコピーした JWT を GARTH_TOKENS_B64 形式に変換するスクリプト。

【手順】
1. Chrome で https://connect.garmin.com を開く（ログイン済みの状態）
2. DevTools を開く (Cmd + Option + I)
3. 「Network」タブを選択
4. ページをリロード (Cmd + R)
5. 左の一覧から「connectapi.garmin.com」へのリクエストを1つクリック
6. 右側の「Headers」→「Request Headers」の中の
   「authorization: Bearer xxxxxx...」の Bearer 以降の文字列をコピー
7. このスクリプトを実行して貼り付ける

使い方:
  python3 scripts/generate_garth_token_from_jwt.py
"""
import base64
import json
import sys
from datetime import datetime, timedelta, timezone


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
    print("（Authorization ヘッダーの「Bearer 」より後ろの文字列）")
    print("=" * 60)

    jwt = input("JWT > ").strip()

    if jwt.lower().startswith("bearer "):
        jwt = jwt[7:].strip()

    if len(jwt) < 50 or jwt.count(".") < 2:
        print("❌ 有効なJWTではありません。「Bearer 」の後ろの文字列のみを貼り付けてください。")
        sys.exit(1)

    payload = decode_jwt_payload(jwt)
    if not payload:
        print("❌ JWTのデコードに失敗しました。")
        sys.exit(1)

    exp = payload.get("exp")
    if exp:
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        expires_in = max(int((expires_at - datetime.now(timezone.utc)).total_seconds()), 0)
        local_exp = expires_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
        if expires_in <= 0:
            print("❌ このJWTはすでに期限切れです。ページをリロードして新しいリクエストのJWTをコピーしてください。")
            sys.exit(1)
        print(f"✓ JWTのデコード成功")
        print(f"  有効期限: {local_exp}（あと {expires_in // 3600}時間 {(expires_in % 3600) // 60}分）")
    else:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        expires_in = 3600
        print("⚠ 有効期限が読み取れませんでした（1時間として設定）")

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
            "access_token": jwt,
            "refresh_token": "",
            "expires_in": expires_in,
            "expires_at": expires_at.isoformat(),
        },
    })

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
        print(f"⚠ 注意: このトークンは {local_exp} に期限切れになります。")
        print("  その後 GitHub Actions が失敗するようであれば、このスクリプトを再実行してください。")


if __name__ == "__main__":
    main()
