#!/bin/bash
# Quick deploy main branch to prod
cd /home/azureuser/finAgent
git pull origin main
cd src && .venv/bin/pip install -e . --quiet
sudo systemctl restart finbestie
echo "Prod updated and restarted ✅"
