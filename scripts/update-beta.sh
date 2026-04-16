#!/bin/bash
# Quick deploy dev branch to beta
cd /home/azureuser/finAgent-beta
git pull origin dev
cd src && .venv/bin/pip install -e . --quiet
# Ensure DEV_MODE and PATH are set in beta service
SVCFILE=/etc/systemd/system/finbestie-beta.service
NEED_RELOAD=0
if ! grep -q 'DEV_MODE' "$SVCFILE" 2>/dev/null; then
  sudo sed -i '/\[Service\]/a Environment=DEV_MODE=1' "$SVCFILE"
  NEED_RELOAD=1
fi
# Add node/gemini to PATH so systemd can find gemini CLI
NVM_BIN=$(dirname "$(which gemini 2>/dev/null || which node 2>/dev/null)")
if [ -n "$NVM_BIN" ] && ! grep -q "$NVM_BIN" "$SVCFILE" 2>/dev/null; then
  sudo sed -i "s|^Environment=PATH=.*||" "$SVCFILE"  # remove old PATH line if any
  sudo sed -i "/\[Service\]/a Environment=PATH=$NVM_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" "$SVCFILE"
  NEED_RELOAD=1
fi
[ "$NEED_RELOAD" = "1" ] && sudo systemctl daemon-reload
sudo systemctl restart finbestie-beta
echo "Beta updated and restarted ✅"
