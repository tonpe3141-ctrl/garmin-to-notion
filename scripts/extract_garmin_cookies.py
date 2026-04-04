"""
Chrome から Garmin Connect の Cookie を自動取得するスクリプト。
手動操作不要。Chrome が開いていても動作する。

使い方:
  cd ~/Projects/garmin-to-notion
  .venv/bin/python3 scripts/extract_garmin_cookies.py
"""
import sys

try:
    import browser_cookie3
except ImportError:
    print("❌ browser-cookie3 が必要です: pip install browser-cookie3")
    sys.exit(1)


TARGET_KEYS = {
    "session", "SESSIONID", "JWT_WEB",
    "GARMIN-SSO", "GARMIN-SSO-CUST-GUID", "GMN_TRACKABLE",
}

GARMIN_DOMAINS = ("garmin.com", "connect.garmin.com", "connectapi.garmin.com")


def main():
    print("Chrome から Garmin Cookie を読み取り中...")
    print("（Keychain へのアクセス許可ダイアログが出たら「許可」を押してください）")
    print()

    try:
        jar = browser_cookie3.chrome(domain_name=".garmin.com")
    except Exception as e:
        print(f"❌ Cookie の読み取りに失敗しました: {e}")
        print("   Chrome を一度再起動してから再試行してください。")
        sys.exit(1)

    cookies = {}
    for c in jar:
        if any(d in c.domain for d in ("garmin.com",)):
            if c.name in TARGET_KEYS:
                cookies[c.name] = c.value

    if not cookies:
        print("⚠ 対象 Cookie が見つかりませんでした。全 Cookie を使います。")
        cookies = {c.name: c.value for c in jar if "garmin.com" in c.domain}

    if not cookies:
        print("❌ Garmin の Cookie が取得できませんでした。")
        print("   Chrome で connect.garmin.com にログインしてから再実行してください。")
        sys.exit(1)

    result = "; ".join(f"{k}={v}" for k, v in cookies.items())

    print(f"✓ {len(cookies)} 個の Cookie を取得しました")
    print()
    print("=" * 60)
    print("GARMIN_SESSION_COOKIES（GitHub Secrets に設定してください）:")
    print("=" * 60)
    print(result)
    print("=" * 60)
    print()
    print("設定方法:")
    print("  GitHub > Settings > Secrets and variables > Actions")
    print("  「New repository secret」で以下を作成:")
    print("  Name : GARMIN_SESSION_COOKIES")
    print("  Value: 上の === で囲まれた文字列をそのまま貼り付け")
    print()
    print("設定後、GitHub Actions を手動実行してください。")


if __name__ == "__main__":
    main()
