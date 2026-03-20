"""
Garth トークンを生成して GitHub Secret 用の base64 文字列を出力するスクリプト。

使い方:
  pip install garminconnect
  python scripts/generate_garth_token.py

出力された文字列を GitHub の Settings > Secrets > GARTH_TOKENS_B64 に登録する。
"""
import getpass
from garminconnect import Garmin

email = input("Garmin email: ")
password = getpass.getpass("Garmin password: ")

print("Logging in to Garmin Connect...")
client = Garmin(email, password)
client.login()

tokens_b64 = client.garth.dumps()
print("\n=== GARTH_TOKENS_B64 (copy this to GitHub Secret) ===")
print(tokens_b64)
print("=====================================================")
print("\nGitHub > Settings > Secrets and variables > Actions > New repository secret")
print("Name: GARTH_TOKENS_B64")
print("Value: (paste above)")
