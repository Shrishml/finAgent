#!/bin/bash
# Quick deploy dev branch to beta
cd /home/azureuser/finAgent-beta
git pull origin dev
cd src && .venv/bin/pip install -e . --quiet
sudo systemctl restart finbestie-beta
echo "Beta updated and restarted ✅"
