#!/usr/bin/env bash
# provision.sh — run ON the VPS: ssh root@<ip> 'bash -s' < deploy/provision.sh
set -euo pipefail

DOMAIN=baromoon.com
APPDIR=/srv/fishwitch

apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git curl >/dev/null

# Caddy = automatic HTTPS reverse proxy
apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https >/dev/null
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
apt-get update -qq && apt-get install -y -qq caddy >/dev/null

# app from the PUBLIC mirror (never the private archive)
if [ ! -d "$APPDIR" ]; then
  git clone https://github.com/SRMillerick/fishwitch.git "$APPDIR"
fi
cd "$APPDIR"
python3 -m venv venv
venv/bin/pip install -q -r requirements.txt

# systemd service — public mode (no FISHWITCH_LOCAL: /review stays off)
cat > /etc/systemd/system/baromoon.service <<EOF
[Unit]
Description=baromoon web
After=network-online.target

[Service]
WorkingDirectory=$APPDIR
# --timeout 120: the History layer can retry the Open-Meteo archive 3×45s on
# a cold cache; gunicorn's 30s default would kill the worker mid-fetch (502).
ExecStart=$APPDIR/venv/bin/gunicorn --workers 2 --threads 4 --bind 127.0.0.1:7700 --timeout 120 --graceful-timeout 30 --access-logfile - webapp:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now baromoon

# warm-cache timer: keeps the weather/history/render caches hot so the first
# visitor gets an instant page (synthetic requests carry ?warm=1 and are not
# counted in page telemetry)
cat > /etc/systemd/system/baromoon-warm.service <<'EOF'
[Unit]
Description=baromoon warm cache (keep the first visitor fast)
After=baromoon.service
Requires=baromoon.service

[Service]
Type=oneshot
ExecStart=/srv/fishwitch/deploy/warm.sh
EOF
cat > /etc/systemd/system/baromoon-warm.timer <<'EOF'
[Unit]
Description=warm baromoon caches every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF
chmod +x "$APPDIR/deploy/warm.sh"
systemctl daemon-reload
systemctl enable --now baromoon-warm.timer

# Caddy site: auto-TLS for the domain, proxy to gunicorn
cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN, www.$DOMAIN {
    encode gzip
    reverse_proxy 127.0.0.1:7700
}
EOF
systemctl restart caddy

# firewall: web + ssh only
command -v ufw >/dev/null && ufw --force reset >/dev/null && ufw allow 22,80,443/tcp >/dev/null && ufw --force enable >/dev/null || true

sleep 2
systemctl is-active baromoon && systemctl is-active caddy
echo "provisioned: https://$DOMAIN (DNS must point here; Caddy issues the cert on first request)"
