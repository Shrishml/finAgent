#!/bin/bash
# Quick deploy dev branch to beta
cd /home/azureuser/finAgent-beta
git pull origin dev
cd src && .venv/bin/pip install -e . --quiet
# Ensure DEV_MODE is set in beta service
if ! grep -q 'DEV_MODE' /etc/systemd/system/finbestie-beta.service 2>/dev/null; then
  sudo sed -i '/Environment=FINBESTIE_DATA/a Environment=DEV_MODE=1' /etc/systemd/system/finbestie-beta.service
  sudo systemctl daemon-reload
fi
sudo systemctl restart finbestie-beta
echo "Beta updated and restarted ✅"
