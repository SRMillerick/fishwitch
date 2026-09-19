# Going live — the runbook

Everything needed to move baromoon from laptop + static snapshot to a public
live app on a small VPS. No secrets exist (no API keys anywhere), which makes
this a clean lift.

## 1. Get a VPS (Sean's move)

Any ~$4–6/mo box: Hetzner CX22, DigitalOcean basic, Linode Nanode.
- Ubuntu 24.04 LTS, 1GB RAM is plenty (gunicorn 2 workers)
- Add your SSH key at creation
- Note the public IP

## 2. Point DNS (Sean's move, Porkbun)

| type | host | value |
|---|---|---|
| `A` | `@` | `<VPS_IP>` (replace the four GitHub Pages A records) |
| `CNAME` | `www` | `baromoon.com` |

## 3. Provision (run once, from anywhere)

```bash
ssh root@<VPS_IP> 'bash -s' < deploy/provision.sh
```

Installs: python3-venv, git, Caddy (auto-HTTPS), clones the public repo into
`/srv/fishwitch` — **the directory name is load-bearing**: the repo root is the
`fishwitch` package and imports resolve relative to it, so `/srv/baromoon` (an
earlier name) breaks the app. Then the venv, deps, systemd service (gunicorn on
127.0.0.1:7700, Caddy proxies 443 → 7700).
Caddy fetches the Let's Encrypt cert on first hit — no certbot config.

## 4. Deploy updates (any time, from ~/fishwitch)

A `baromoon-warm.timer` (installed by `provision.sh`) runs `deploy/warm.sh` every 15 min to keep
the in-memory weather/history/render caches hot, so the first visitor never waits; synthetic
requests carry `?warm=1` and are excluded from page telemetry.

```bash
./deploy/deploy.sh          # = publish-mirror, then ssh pull + restart
```

The VPS tracks the PUBLIC repo (clean mirror) — never the private archive.

Traffic and monetization telemetry live on the VPS under `/srv/fishwitch/logs/` and are read
from the dev box over ssh: `fishwitch stats --remote` (page views) and `fishwitch clicks --remote`
(outbound clicks). Plain `stats`/`clicks` read the local dev log.

## 5. Post-launch checklist

- [ ] https://baromoon.com renders the ledger
- [ ] /privacy /disclosure /contact live (Associates requirement)
- [ ] Porkbun email forwarding: hello@baromoon.com → Sean
- [ ] Apply: Amazon Associates (needs the live site + contact email)
- [ ] Apply: Tackle Warehouse affiliate (parallel)
- [ ] Optional: an uptime pinger (UptimeRobot free) on /
- [ ] Home-laptop service can stay as the "local mode" instance (FISHWITCH_LOCAL=1 there, /review live) — the VPS runs public-safe only

## What the VPS never holds

Profiles (browser vault), logbook (local file), review panel (LOCAL-gated),
any birth data. If the box is compromised, there's nothing personal to take.
