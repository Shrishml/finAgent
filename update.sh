#!/bin/bash
# FinBestie quick update: pull latest code + restart app
# Usage: ./update.sh
set -e

APP_DIR="$HOME/finAgent"
LOG="/tmp/finbestie.log"

echo "📦 Pulling latest code..."
cd "$APP_DIR"
git pull origin dev

echo "🔄 Restarting app..."
pkill -f 'finagent.main' 2>/dev/null || true
sleep 1

cd src
source .venv/bin/activate
pip install -e . -q 2>&1
nohup python -m finagent.main > "$LOG" 2>&1 &
sleep 3

# Verify
if curl -sf http://localhost:8000/auth/me > /dev/null 2>&1; then
    echo "✅ FinBestie is running. Logs: $LOG"
else
    echo "⚠️  Check logs: tail -f $LOG"
fi
