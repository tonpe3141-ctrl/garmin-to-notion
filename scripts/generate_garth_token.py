"""
Garth トークンを生成して GitHub Secret 用の base64 文字列を出力するスクリプト。

使い方:
  pip install garminconnect
  python scripts/generate_garth_token.py

出力された文字列を GitHub の Settings > Secrets > GARTH_TOKENS_B64 に登録する。

429 (Too Many Requests) エラーが出た場合は指数バックオフで自動リトライします。
それでも失敗する場合は、ブラウザ版を使ってください:
  python scripts/generate_garth_token_browser.py
"""
import getpass
import os
import sys
import time

from garminconnect import Garmin

# リトライ設定
MAX_RETRIES = 4
INITIAL_BACKOFF_SECONDS = 30  # 30s → 60s → 120s → 240s

TOKEN_DIR = os.path.expanduser("~/.garth")


def login_with_retry(email: str, password: str) -> Garmin:
    """指数バックオフ付きでログインを試行する。"""
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"\n[{attempt}/{MAX_RETRIES}] Garmin Connect にログイン中...")
            client = Garmin(email, password)
            client.login()
            return client
        except Exception as e:
            last_error = e
            error_str = str(e)

            if "429" in error_str or "Too Many Requests" in error_str:
                if attempt < MAX_RETRIES:
                    wait = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    print(f"  ⚠ 429 レートリミット検出。{wait}秒待機して再試行します...")
                    time.sleep(wait)
                else:
                    print(f"  ✗ {MAX_RETRIES}回リトライしましたが、レートリミットが解除されません。")
            else:
                # 429 以外のエラーは即座に失敗
                print(f"  ✗ ログイン失敗: {e}")
                break

    print("\n" + "=" * 60)
    print("❌ ログインに失敗しました。")
    print()
    print("対処法:")
    print("  1. しばらく待ってから再実行してください（数時間～1日）")
    print("  2. ブラウザ版のトークン生成を試してください:")
    print("     python scripts/generate_garth_token_browser.py")
    print("  3. 手動でブラウザからJWTを取得:")
    print("     python scripts/generate_garth_token_from_jwt.py")
    print("=" * 60)
    raise last_error


def main():
    email = input("Garmin email: ")
    password = getpass.getpass("Garmin password: ")

    client = login_with_retry(email, password)

    # トークンを ~/.garth に保存（次回の再ログイン不要）
    os.makedirs(TOKEN_DIR, exist_ok=True)
    client.garth.dump(TOKEN_DIR)
    print(f"\n✓ トークンを {TOKEN_DIR} に保存しました（次回はキャッシュから認証可能）")

    # GitHub Secret 用の文字列を出力
    tokens_b64 = client.garth.dumps()
    print("\n=== GARTH_TOKENS_B64 (copy this to GitHub Secret) ===")
    print(tokens_b64)
    print("=====================================================")
    print("\nGitHub > Settings > Secrets and variables > Actions > New repository secret")
    print("Name: GARTH_TOKENS_B64")
    print("Value: (paste above)")


if __name__ == "__main__":
    main()
