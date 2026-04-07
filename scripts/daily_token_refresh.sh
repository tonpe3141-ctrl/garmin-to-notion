#!/bin/bash
# Garmin トークンを毎日自動更新してGitHub Secretsにアップロードするスクリプト。
# launchd (macOS cron) から実行される。
# 実行タイミング: 毎日 7:00 AM JST（GitHub Actions 実行の1.5時間前）

set -e

PROJECT_DIR="$HOME/Projects/garmin-to-notion"
PYTHON="$PROJECT_DIR/.venv/bin/python3"
LOG_FILE="$HOME/Library/Logs/garmin-token-refresh.log"
REPO="tonpe3141-ctrl/garmin-to-notion"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Garmin トークン自動更新開始 ==="

# .env から認証情報を読み込む
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | grep -E '^GARMIN_(EMAIL|PASSWORD)=' | xargs)
fi

if [ -z "$GARMIN_EMAIL" ] || [ -z "$GARMIN_PASSWORD" ]; then
    log "ERROR: GARMIN_EMAIL / GARMIN_PASSWORD が未設定"
    exit 1
fi

# 1. トークン生成
log "Garmin にログインしてトークンを生成中..."
cd "$PROJECT_DIR"
if ! "$PYTHON" scripts/refresh_garth_tokens.py >> "$LOG_FILE" 2>&1; then
    log "ERROR: トークン生成に失敗しました"
    exit 1
fi

# 2. GitHub Secret を更新
log "GitHub Secret (GARTH_TOKENS_B64) を更新中..."
GITHUB_TOKEN=$(security find-internet-password -s github.com -w 2>/dev/null || echo "")

if [ -z "$GITHUB_TOKEN" ]; then
    log "WARNING: GitHub トークンがキーチェーンに見つかりません。手動更新が必要です。"
    log "トークンは /tmp/garth_fresh_tokens.txt に保存されています。"
    exit 0
fi

GARTH_TOKENS=$(cat /tmp/garth_fresh_tokens.txt)

"$PYTHON" - "$GITHUB_TOKEN" "$REPO" "$GARTH_TOKENS" >> "$LOG_FILE" 2>&1 <<'PYEOF'
import sys, json, base64, requests
from nacl import encoding, public

token = sys.argv[1]
repo = sys.argv[2]
secret_value = sys.argv[3]

headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
r = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=headers, timeout=15)
key_data = r.json()
pub_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
box = public.SealedBox(pub_key)
encrypted = base64.b64encode(box.encrypt(secret_value.encode("utf-8"))).decode("utf-8")
r2 = requests.put(
    f"https://api.github.com/repos/{repo}/actions/secrets/GARTH_TOKENS_B64",
    headers=headers, json={"encrypted_value": encrypted, "key_id": key_data["key_id"]}, timeout=15,
)
if r2.status_code in (201, 204):
    print("✓ GARTH_TOKENS_B64 を更新しました")
else:
    print(f"✗ 更新失敗: {r2.status_code} {r2.text}")
    sys.exit(1)
PYEOF

log "=== 完了 ==="
