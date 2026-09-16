#!/bin/sh
# deploy.sh — ship the latest public mirror to the VPS and restart
# Usage: BAROMOON_HOST=root@<vps-ip> ./deploy/deploy.sh   (or edit the default)
set -e
DIR="$(dirname "$(readlink -f "$0")")/.."
cd "$DIR"

HOST="${BAROMOON_HOST:-root@$(cat deploy/host.txt 2>/dev/null || echo SET-BAROMOON_HOST)}"
echo "→ mirroring public repo…"
./publish-mirror
echo "→ pulling on $HOST and restarting…"
ssh "$HOST" 'cd /srv/fishwitch && git pull -q && systemctl restart baromoon && systemctl is-active baromoon'
echo "✅ live"
