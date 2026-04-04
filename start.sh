#!/bin/bash
set -e
cd "$(dirname "$0")/src"

echo "🔍 Checking Python..."
python3 --version 2>/dev/null | grep -qE "3\.(1[1-9]|[2-9][0-9])" || {
    echo "❌ Python 3.11+ required. Found: $(python3 --version 2>&1)"
    exit 1
}
echo "✅ $(python3 --version)"

# Create venv if needed
if [ ! -d .venv ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# Install deps
echo "📦 Installing dependencies..."
pip install -e . 2>&1 || { echo "❌ Dependency install failed"; exit 1; }

# Check LLM CLI
echo ""
echo "🤖 Checking LLM providers..."
if command -v kiro-cli &>/dev/null; then
    echo "✅ kiro-cli found"
elif command -v claude &>/dev/null; then
    echo "✅ claude CLI found"
elif command -v gemini &>/dev/null; then
    echo "✅ gemini CLI found"
else
    echo "⚠️  No LLM CLI found. Install kiro-cli, claude, or gemini CLI."
    echo "   Or configure an API key in config.toml"
fi

# Default config
if [ ! -f config.toml ]; then
    echo "📝 Creating default config..."
    cp config.toml.example config.toml
fi

# Launch
echo ""
echo "🚀 Starting FinAgent on http://localhost:8000"
python -m finagent.main
