#!/bin/bash
# Arth server deployment: nginx reverse proxy + HTTPS
# Usage: sudo ./deploy.sh [email@example.com]
set -e

DOMAIN="askarth.com"
EMAIL="${1:-admin@$DOMAIN}"
APP_PORT=8000

echo "🔧 Setting up $DOMAIN → localhost:$APP_PORT"

# Install nginx + certbot
if command -v apt &>/dev/null; then
    apt update -qq && apt install -y -qq nginx certbot python3-certbot-nginx
elif command -v yum &>/dev/null; then
    yum install -y nginx certbot python3-certbot-nginx
else
    echo "❌ Unsupported package manager"; exit 1
fi

# Write nginx config
cat > /etc/nginx/sites-available/arth <<EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_read_timeout 300;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

# Enable site
ln -sf /etc/nginx/sites-available/arth /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo "✅ Nginx configured. http://$DOMAIN should work now."

# SSL
read -p "🔒 Set up HTTPS with Let's Encrypt? [Y/n] " ssl
if [[ "${ssl:-Y}" =~ ^[Yy]$ ]]; then
    certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos -m "$EMAIL"
    echo "✅ HTTPS enabled. https://$DOMAIN is live!"
else
    echo "⏭️  Skipped HTTPS. Run later: sudo certbot --nginx -d $DOMAIN"
fi

echo ""
echo "🎉 Done! Your app is live at http://$DOMAIN"
