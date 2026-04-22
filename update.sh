#!/bin/bash
# Arth update: pull latest + ensure env + restart
# Usage: ./update.sh
set -e

APP_DIR="$HOME/finAgent"
SRC_DIR="$APP_DIR/src"
LOG="/tmp/arth.log"

cd "$APP_DIR"

# 1. Pull latest
echo "📦 Pulling latest code..."
git pull origin dev

# 2. Stop existing process
echo "🛑 Stopping app..."
pkill -f 'finagent.main' 2>/dev/null || true
sleep 1

# 3. Find Python 3.11+
cd "$SRC_DIR"
PY=""
for cmd in python3.11 python3.12 python3.13 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(sys.version_info.minor)')
        if [ "$ver" -ge 11 ] 2>/dev/null; then
            PY="$cmd"
            break
        fi
    fi
done
if [ -z "$PY" ]; then
    echo "❌ Python 3.11+ required but not found"
    exit 1
fi
echo "✅ Using $PY ($($PY --version))"

# 4. Create venv if missing
if [ ! -d .venv ]; then
    echo "📦 Creating virtual environment..."
    $PY -m venv .venv
fi
source .venv/bin/activate

# 5. Install/update deps
echo "📦 Installing dependencies..."
pip install -e . -q 2>&1

# 6. Start app
echo "🚀 Starting Arth..."
nohup python -m finagent.main > "$LOG" 2>&1 &
sleep 3

# 7. Verify
if curl -sf http://localhost:8000/auth/me > /dev/null 2>&1; then
    echo "✅ Arth is running at http://localhost:8000"
else
    echo "⚠️  Startup may have failed. Logs:"
    tail -10 "$LOG"
fi
