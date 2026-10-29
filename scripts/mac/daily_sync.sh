#!/bin/bash
# Garmin のデータを取ってドライブへ書く（毎朝。Mac の launchd から呼ばれる）。
#
# GitHub Actions からは Garmin のログインが弾かれる（2026-10-28〜。Cloudflare の人間確認・403・429）。
# 家の回線の Mac から取れば、普通のログインとして通る。
#
# launchd は 7:30 / 9:30 / 11:30 に呼ぶ。スリープ中に時刻が過ぎた分は、起きたときに1回呼ばれる。
# その日すでに成功していれば何もしない（--force で強制実行）。
#
# 入れ方: scripts/mac/install.sh を1回実行する。ログ: ~/Library/Logs/garmin-sync.log

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python3"
LOG_FILE="$HOME/Library/Logs/garmin-sync.log"
STATE_DIR="$HOME/Library/Application Support/garmin-sync"
DONE_FILE="$STATE_DIR/last_success"
LOCK_DIR="$STATE_DIR/lock"

export TZ=Asia/Tokyo
TODAY=$(date +%F)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

notify() {
    osascript -e "display notification \"$1\" with title \"Garmin 同期\"" >/dev/null 2>&1 || true
}

mkdir -p "$STATE_DIR" "$(dirname "$LOG_FILE")"

if [ "$1" != "--force" ] && [ "$(cat "$DONE_FILE" 2>/dev/null)" = "$TODAY" ]; then
    exit 0
fi

# 同時に2つ走らせない。落ちて残ったロックは1時間で捨てる。
if [ -d "$LOCK_DIR" ] && [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +60)" ]; then
    rmdir "$LOCK_DIR"
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    log "別の同期が実行中のためスキップ"
    exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

log "=== 同期開始 ==="
cd "$PROJECT_DIR" || exit 1

# 実行中はスリープさせない
if caffeinate -i "$PYTHON" src/ガーミン活動データ取得.py >> "$LOG_FILE" 2>&1; then
    echo "$TODAY" > "$DONE_FILE"
    log "=== 同期成功 ==="
else
    log "=== 同期失敗（次の時刻にもう一度試す） ==="
    notify "Garmin の同期に失敗しました。ログ: ~/Library/Logs/garmin-sync.log"
    exit 1
fi
