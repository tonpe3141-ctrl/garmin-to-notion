"""
Chrome の「Copy as cURL」からGarmin Cookieを抽出するスクリプト。

【手順】
1. Chrome で connect.garmin.com を開く（ログイン済み）
2. DevTools → Network タブ → Cmd+R でリロード
3. 一覧に出たリクエストを何でもいいので右クリック
4. 「Copy」→「Copy as cURL (bash)」
5. このスクリプトを実行して貼り付ける

使い方:
  python3 scripts/extract_garmin_cookies.py
"""
import re
import sys


def extract_cookie_from_curl(curl_cmd: str) -> str:
    # -H 'cookie: ...' 形式
    m = re.search(r"-H\s+'[Cc]ookie:\s*([^']+)'", curl_cmd)
    if m:
        return m.group(1).strip()
    # -H "cookie: ..." 形式
    m = re.search(r'-H\s+"[Cc]ookie:\s*([^"]+)"', curl_cmd)
    if m:
        return m.group(1).strip()
    # -b '...' 形式（Chrome が使う形式）
    m = re.search(r"\s-b\s+'([^']+)'", curl_cmd)
    if m:
        return m.group(1).strip()
    m = re.search(r'\s-b\s+"([^"]+)"', curl_cmd)
    if m:
        return m.group(1).strip()
    # --cookie 形式
    m = re.search(r"--cookie\s+'([^']+)'", curl_cmd)
    if m:
        return m.group(1).strip()
    return ""


def main():
    print("=" * 60)
    print("Garmin Cookie 抽出ツール")
    print("=" * 60)
    print()
    print("手順:")
    print("  1. Chrome で connect.garmin.com を開く（ログイン済み）")
    print("  2. DevTools（Cmd+Option+I）→ Network タブ")
    print("  3. Cmd+R でリロード")
    print("  4. 一覧の最初のリクエストを右クリック")
    print("     → Copy → Copy as cURL (bash)")
    print("  5. 下に貼り付けて Enter → 空行で Enter")
    print()
    print("cURL コマンドを貼り付けてください（空行2回で完了）:")
    print()

    lines = []
    empty_count = 0
    while True:
        try:
            line = input()
            if line == "":
                empty_count += 1
                if empty_count >= 1 and lines:
                    break
            else:
                empty_count = 0
                lines.append(line)
        except EOFError:
            break

    curl_cmd = " ".join(lines)

    if not curl_cmd.strip():
        print("❌ 入力がありませんでした。")
        sys.exit(1)

    cookie_str = extract_cookie_from_curl(curl_cmd)

    if not cookie_str:
        print("❌ Cookie ヘッダーが見つかりませんでした。")
        print("   cURL コマンド全体を貼り付けてください。")
        sys.exit(1)

    # garmin.com 関連のCookieだけ抽出（不要なものを省く）
    garmin_keys = {
        "session", "SESSIONID", "JWT_WEB", "GARMIN-SSO",
        "GARMIN-SSO-CUST-GUID", "GMN_TRACKABLE",
    }
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            if k in garmin_keys:
                cookies[k] = v.strip()

    if not cookies:
        # Garmin系が見つからなければ全部使う
        result = cookie_str
    else:
        result = "; ".join(f"{k}={v}" for k, v in cookies.items())

    print()
    print(f"✓ Cookie 取得成功（{len(result)} 文字、{len(cookies)} 項目）")
    print()
    print("=" * 60)
    print("GARMIN_SESSION_COOKIES（GitHub Secrets に設定してください）:")
    print("=" * 60)
    print(result)
    print("=" * 60)
    print()
    print("設定方法:")
    print("  GitHub > Settings > Secrets and variables > Actions")
    print("  「New repository secret」→ Name: GARMIN_SESSION_COOKIES")
    print("  Value: 上記の文字列をそのまま貼り付け")
    print()
    print("設定後、GitHub Actions を手動実行してください。")
    print("（GARTH_TOKENS_B64 は不要になります）")


if __name__ == "__main__":
    main()
