"""
cloudscraper を使って Garmin Connect にログインし、
GARTH_TOKENS_B64 を更新するスクリプト。

garth の標準 login() が 429 レート制限でブロックされる場合に使用。
cloudscraper が CloudFlare を回避しながら旧 SSO エンドポイントを叩く。

使い方:
  cd ~/Projects/garmin-to-notion
  source .env
  .venv/bin/python3 scripts/refresh_garth_tokens.py

環境変数:
  GARMIN_EMAIL    - Garmin アカウントのメールアドレス
  GARMIN_PASSWORD - Garmin アカウントのパスワード
"""
import base64
import json
import os
import re
import sys
import time
from urllib.parse import parse_qs

try:
    import cloudscraper
except ImportError:
    print("❌ cloudscraper が必要です: pip install cloudscraper")
    sys.exit(1)

try:
    from requests_oauthlib import OAuth1Session
except ImportError:
    print("❌ requests-oauthlib が必要です: pip install requests-oauthlib")
    sys.exit(1)

EMAIL = os.environ.get("GARMIN_EMAIL", "")
PASSWORD = os.environ.get("GARMIN_PASSWORD", "")

if not EMAIL or not PASSWORD:
    print("❌ GARMIN_EMAIL / GARMIN_PASSWORD 環境変数が未設定です")
    sys.exit(1)

OAUTH_CONSUMER_URL = "https://thegarth.s3.amazonaws.com/oauth_consumer.json"
SSO = "https://sso.garmin.com/sso"
SSO_EMBED = f"{SSO}/embed"
SSO_EMBED_PARAMS = {"id": "gauth-widget", "embedWidget": "true", "gauthHost": SSO}
SIGNIN_PARAMS = {
    **SSO_EMBED_PARAMS,
    "gauthHost": SSO_EMBED,
    "service": SSO_EMBED,
    "source": SSO_EMBED,
    "redirectAfterAccountLoginUrl": SSO_EMBED,
    "redirectAfterAccountCreationUrl": SSO_EMBED,
}
UA = "com.garmin.android.apps.connectmobile"


def create_scraper():
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "desktop": True}
    )
    s.headers.update({"User-Agent": UA})
    return s


def get_service_ticket(scraper):
    """旧 SSO エンドポイントを使ってサービスチケットを取得する。"""
    print("[1] GET /sso/embed ...")
    r = scraper.get(SSO_EMBED, params=SSO_EMBED_PARAMS, timeout=20)
    r.raise_for_status()
    time.sleep(1)

    print("[2] GET /sso/signin ...")
    r = scraper.get(
        f"{SSO}/signin",
        params=SIGNIN_PARAMS,
        headers={"Referer": SSO_EMBED},
        timeout=20,
    )
    r.raise_for_status()

    csrf = (re.search(r'name="_csrf"\s+value="(.+?)"', r.text) or [None, None])[1]
    if not csrf:
        raise RuntimeError("CSRF トークンが見つかりませんでした")
    print(f"    CSRF: 取得成功")
    time.sleep(1)

    print("[3] POST /sso/signin (ログイン) ...")
    r = scraper.post(
        f"{SSO}/signin",
        params=SIGNIN_PARAMS,
        headers={
            "Referer": f"{SSO}/signin",
            "Origin": "https://sso.garmin.com",
        },
        data={
            "username": EMAIL,
            "password": PASSWORD,
            "embed": "true",
            "_csrf": csrf,
        },
        timeout=20,
    )

    if r.status_code == 429:
        raise RuntimeError(
            "429 レート制限。しばらく待ってから再試行してください（数分〜数時間）"
        )
    r.raise_for_status()

    title = (re.search(r"<title>(.+?)</title>", r.text) or [None, "?"])[1]
    if title != "Success":
        raise RuntimeError(f"ログイン失敗: title={title}\n{r.text[:300]}")

    ticket_m = re.search(r'embed\?ticket=([^"&\s]+)', r.text)
    if not ticket_m:
        raise RuntimeError("サービスチケットが見つかりません")

    ticket = ticket_m.group(1)
    print(f"    チケット取得: {ticket[:30]}...")
    return ticket


def exchange_ticket_for_oauth1(ticket, scraper):
    """チケットを OAuth1 トークンに交換する。"""
    print("[4] OAuth コンシューマー資格情報を取得 ...")
    oauth_consumer = scraper.get(OAUTH_CONSUMER_URL, timeout=10).json()

    print("[5] チケット → OAuth1 トークン ...")
    oauth1_sess = OAuth1Session(
        oauth_consumer["consumer_key"], oauth_consumer["consumer_secret"]
    )
    for c in scraper.cookies:
        oauth1_sess.cookies.set(c.name, c.value, domain=c.domain or "garmin.com")
    oauth1_sess.headers["User-Agent"] = UA

    preauth_url = (
        f"https://connectapi.garmin.com/oauth-service/oauth/preauthorized"
        f"?ticket={ticket}"
        f"&login-url=https://sso.garmin.com/sso/embed"
        f"&accepts-mfa-tokens=true"
    )
    resp = oauth1_sess.get(preauth_url, timeout=20)
    resp.raise_for_status()

    parsed = parse_qs(resp.text)
    oauth_token = parsed.get("oauth_token", [""])[0]
    oauth_secret = parsed.get("oauth_token_secret", [""])[0]

    if not oauth_token:
        raise RuntimeError(f"OAuth1 トークン取得失敗: {resp.text[:200]}")

    print(f"    oauth_token: 取得成功")
    return oauth_token, oauth_secret, oauth_consumer


def exchange_oauth1_for_oauth2(oauth_token, oauth_secret, oauth_consumer):
    """OAuth1 トークンを OAuth2 アクセストークンに交換する。"""
    print("[6] OAuth1 → OAuth2 ...")
    oauth2_sess = OAuth1Session(
        oauth_consumer["consumer_key"],
        oauth_consumer["consumer_secret"],
        resource_owner_key=oauth_token,
        resource_owner_secret=oauth_secret,
    )
    oauth2_sess.headers["User-Agent"] = UA

    resp = oauth2_sess.post(
        "https://connectapi.garmin.com/oauth-service/oauth/exchange/user/2.0",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def build_garth_dump(oauth_token, oauth_secret, token_data):
    """garth.dumps() 互換の base64 文字列を生成する。"""
    now_ts = int(time.time())
    exp_in = int(token_data.get("expires_in", 3600))
    exp_at = now_ts + exp_in
    rt_exp_in = int(token_data.get("refresh_token_expires_in", 90 * 24 * 3600))
    rt_exp_at = now_ts + rt_exp_in

    oauth1_dict = {
        "oauth_token": oauth_token,
        "oauth_token_secret": oauth_secret,
        "mfa_token": None,
        "mfa_expiration_timestamp": None,
        "domain": "garmin.com",
    }
    oauth2_dict = {
        "scope": token_data.get("scope", ""),
        "jti": token_data.get("jti", ""),
        "token_type": "Bearer",
        "access_token": token_data.get("access_token", ""),
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_in": exp_in,
        "expires_at": exp_at,
        "refresh_token_expires_in": rt_exp_in,
        "refresh_token_expires_at": rt_exp_at,
    }
    return base64.b64encode(json.dumps([oauth1_dict, oauth2_dict]).encode()).decode(), oauth1_dict, oauth2_dict


def main():
    print("=" * 60)
    print("  Garmin トークン更新ツール（cloudscraper版）")
    print("=" * 60)
    print()

    scraper = create_scraper()

    # 1回試行、429 の場合は少し待って再試行
    ticket = None
    for attempt in range(2):
        try:
            ticket = get_service_ticket(scraper)
            break
        except RuntimeError as e:
            if "429" in str(e) and attempt == 0:
                print(f"    {e}")
                print("    60秒待機して再試行します...")
                time.sleep(60)
                scraper = create_scraper()
            else:
                print(f"❌ {e}")
                sys.exit(1)

    oauth_token, oauth_secret, oauth_consumer = exchange_ticket_for_oauth1(ticket, scraper)
    token_data = exchange_oauth1_for_oauth2(oauth_token, oauth_secret, oauth_consumer)

    garth_dump, oauth1_dict, oauth2_dict = build_garth_dump(oauth_token, oauth_secret, token_data)

    # ~/.garth に保存
    import os
    garth_dir = os.path.expanduser("~/.garth")
    os.makedirs(garth_dir, exist_ok=True)
    with open(os.path.join(garth_dir, "oauth1_token.json"), "w") as f:
        json.dump(oauth1_dict, f, indent=2)
    with open(os.path.join(garth_dir, "oauth2_token.json"), "w") as f:
        json.dump(oauth2_dict, f, indent=2)

    # /tmp に保存（GitHub Actions 自動更新用）
    with open("/tmp/garth_fresh_tokens.txt", "w") as f:
        f.write(garth_dump)

    exp_at = oauth2_dict["expires_at"]
    from datetime import datetime, timezone
    local_exp = datetime.fromtimestamp(exp_at, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")

    print()
    print("=" * 60)
    print("✅ トークン取得成功！")
    print("=" * 60)
    print(f"  有効期限: {local_exp}")
    print(f"  保存先: {garth_dir}/")
    print()
    print("GARTH_TOKENS_B64（GitHub Secrets に設定してください）:")
    print("-" * 60)
    print(garth_dump)
    print("-" * 60)
    print()
    print("GitHub Secret 自動更新:")
    print("  GitHub Actions の GH_PAT_SECRETS が設定済みであれば、")
    print("  次回のワークフロー実行時に自動更新されます。")
    print()
    print("手動設定方法:")
    print("  GitHub > Settings > Secrets and variables > Actions")
    print("  GARTH_TOKENS_B64 の値を上記で上書き")


if __name__ == "__main__":
    main()
