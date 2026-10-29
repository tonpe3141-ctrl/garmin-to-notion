#!/bin/bash
# Mac で毎朝の Garmin 同期を動かすための設定（1回だけ実行する）。
#
#   bash scripts/mac/install.sh
#
# やること:
#   1. .env に Garmin と Google の設定があるか確かめる
#   2. .venv が無ければ作って依存を入れる
#   3. launchd に登録する（7:30 / 9:30 / 11:30。その日成功したら残りは何もしない）
#   4. その場で1回同期して、ドライブが更新されるか確かめる
#
# やめるとき: launchctl bootout gui/$(id -u)/com.tonpe3141.garmin-sync
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.tonpe3141.garmin-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
ENV_FILE="$PROJECT_DIR/.env"

echo "プロジェクト: $PROJECT_DIR"

# 1. .env
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ $ENV_FILE がありません。.example.env をコピーして値を入れてください。"
    exit 1
fi
for key in GARMIN_EMAIL GARMIN_PASSWORD GOOGLE_SERVICE_ACCOUNT_JSON GOOGLE_DRIVE_FOLDER_ID; do
    val=$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2-)
    if [ -z "$val" ] || [ "$val" = "CHANGEME" ]; then
        echo "❌ .env の $key が未設定です。"
        echo "   GOOGLE_SERVICE_ACCOUNT_JSON にはサービスアカウントの鍵ファイルのパス（例: ~/.config/garmin/service-account.json）を書けます。"
        exit 1
    fi
done
echo "✓ .env OK"

# 2. Python 環境（garminconnect は 3.10 以上が必要）
if [ ! -x "$PROJECT_DIR/.venv/bin/python3" ]; then
    PY=""
    for cand in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cand" >/dev/null && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
            PY="$cand"; break
        fi
    done
    if [ -z "$PY" ]; then
        echo "❌ Python 3.10 以上が見つかりません（brew install python@3.12 など）。"
        exit 1
    fi
    echo "→ .venv を作成（$PY）"
    "$PY" -m venv "$PROJECT_DIR/.venv"
fi
"$PROJECT_DIR/.venv/bin/pip" install -q --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install -q -r "$PROJECT_DIR/requirements.txt"
echo "✓ 依存パッケージ OK"

chmod +x "$PROJECT_DIR/scripts/mac/daily_sync.sh"

# 3. launchd
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$PROJECT_DIR/scripts/mac/daily_sync.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>30</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/garmin-sync.launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/garmin-sync.launchd.log</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "✓ launchd に登録しました（$PLIST）"

# 4. 試しに1回
echo "→ 試しに同期します（数分かかります。ログ: ~/Library/Logs/garmin-sync.log）"
if /bin/bash "$PROJECT_DIR/scripts/mac/daily_sync.sh" --force; then
    echo "✓ 同期成功。Google ドライブの「Garmin Running Log (Document)」の先頭行の日時を確かめてください。"
else
    echo "❌ 同期に失敗しました。~/Library/Logs/garmin-sync.log の末尾を見てください。"
    tail -30 "$HOME/Library/Logs/garmin-sync.log"
    exit 1
fi
