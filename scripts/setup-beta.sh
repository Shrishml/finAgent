#!/bin/bash
# Run this on the Azure VM (20.98.218.146) as azureuser
# Sets up beta.captwist.in alongside prod captwist.in
set -e

echo "=== 1. Clone beta instance ==="
cd /home/azureuser
if [ -d finAgent-beta ]; then
  echo "finAgent-beta already exists, pulling latest..."
  cd finAgent-beta && git pull origin dev && cd ..
else
  git clone -b dev https://github.com/Suraj1074/finAgent.git finAgent-beta
fi

echo "=== 2. Set up beta venv ==="
cd finAgent-beta/src
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]" --quiet

echo "=== 3. Create beta data directory ==="
mkdir -p /home/azureuser/finAgent-beta/data

echo "=== 4. Create beta systemd service ==="
sudo tee /etc/systemd/system/finbestie-beta.service > /dev/null <<'EOF'
[Unit]
Description=FinBestie Beta (dev branch)
After=network.target

[Service]
User=azureuser
WorkingDirectory=/home/azureuser/finAgent-beta/src
ExecStart=/home/azureuser/finAgent-beta/src/.venv/bin/uvicorn finagent.main:app --host 127.0.0.1 --port 8001
Restart=always
Environment=FINBESTIE_DATA=/home/azureuser/finAgent-beta/data

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable finbestie-beta
sudo systemctl start finbestie-beta

echo "=== 5. Create nginx config for beta ==="
sudo tee /etc/nginx/sites-available/beta.captwist.in > /dev/null <<'EOF'
server {
    listen 80;
    server_name beta.captwist.in;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/beta.captwist.in /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

echo "=== 6. SSL certificate ==="
sudo certbot --nginx -d beta.captwist.in --non-interactive --agree-tos --redirect

echo "=== Done! ==="
echo "Beta running at https://beta.captwist.in (port 8001, dev branch)"
echo "Prod unchanged at https://captwist.in (port 8000, main branch)"
