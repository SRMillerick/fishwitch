# Going live — the runbook

The existing VPS deployment uses a sanitized public source mirror. The private
archive is the development/rollback history and must never be pushed publicly.
Initial provisioning instructions below are historical setup guidance, not a
reason to reprovision or upgrade the running site.

## Live release — 2026-10-24

Deployed at **13:45:48 UTC** through `./deploy/deploy.sh`:

| Role | Revision |
| --- | --- |
| Private source checkpoint | `f062af2719c62846cfaa42acda4a6c240e924c1f` |
| Sanitized public mirror / deployed pinned HEAD | `4606bcc270bb2d7ac5178c32bcf76777ea22db53` |
| Previous public revision / rollback target | `b399628afa376ad8b882a7af1427437d43b553be` |
| Unchanged static gh-pages | `320c3bb59e24b5b46a1167683f6c43fcecbe2760` |

**Initial production acceptance passed; no recovery was needed.** HTTPS serves
the new calculation-free form. Synthetic personal/shared calculations and place
lookup pass; results/errors are `no-store`, and invalid/oversized requests return
400/413. The real production v3 worker was installed in a disposable browser
before cutover; afterward v4 updated, purged old caches, preserved the synthetic
vault, imported it explicitly and rendered a result at 375px without birth data
in URLs or third-party new-page requests. Home/API are absent from Cache Storage.

Active proxy/service configuration and synthetic log probes show no request-body
capture; ordinary IP/path/status/UA access logging remains. A spoofed forwarded-IP
probe confirms the single trusted proxy hop. Venv/profile hashes and inodes and
log inodes survived; Caddy's PID is unchanged, all three services/timer are active,
and production still has no tracked edits (preserve untracked `venv/`).

Small performance samples: HTTPS form **144.3 ms median** (n=5); personal API
**197.2 ms median, 941.4 ms max** (n=4); frozen six-day core **61.58 ms median,
109.10 ms max** on the VPS (n=12). Not a load test, SLA or controlled cold-cache
audit. Unavailable/excluded, redacted 503 and 429 states were tested separately in
an isolated process using deployed code with network blocked, **not by injecting
faults into live workers**. The retained `/legacy` route still takes ~15 seconds
cold and still uses old enrichment; do not conflate it with new-core latency.

Both private and exact sanitized release trees pass **374 offline Python tests,
20 window JS scenarios, eight legacy JS scenarios and real Chromium acceptance**.
Check exclusions on the pristine prepared tree, before tests generate synthetic
runtime logs. The release ran the existing IndexNow ping (200, 130 URLs), but did
not publish the static snapshot, change DNS, add dependencies/services/spending or
retire legacy consumers. The first natural warmer ran **13:56:06–13:56:32 UTC**,
exit 0, with **all six HTTP responses confirmed 200** in the access log. The new
form stayed healthy and no worker traceback/timeout appeared through that run.
Continue observation; this is not long-running stability/privacy proof.

The post-release record is a private documentation checkpoint, not another deploy.
See the latest private handoff for full evidence and future stabilization notes.

## Release and rollback procedure — prepared 2026-10-24

`deploy.sh` now supports a pinned public-revision rollback, with local HTTP/service
health checks and automatic recovery to the preceding deployed revision. The
external HTTPS gate also invokes that same recovery path on failure. Release
operations are host-locked and reject a changed revision since preflight, tracked
production edits, a non-public origin, non-public target commits, and changed
`requirements.txt`. Code/assets are checked out at a detached public commit;
**no branch is force-pushed, no `git clean`/hard reset, and no venv update occurs.**
Ignored/untracked runtime files are preserved, including on a checkout collision.
The helper is streamed from the dev box, so old target revisions need not contain it.

```bash
./deploy/deploy.sh --check     # read-only production Git/origin check, no publication
./deploy/deploy.sh             # clean + privately pushed HEAD → sanitized public mirror → pinned release
# Known preceding production revision (record a fresh value before each release):
./deploy/deploy.sh --rollback b399628afa376ad8b882a7af1427437d43b553be
```

Rollback does **not** republish either repository or the static snapshot. Public
main can remain newer than the pinned deployed revision. The next normal deploy
fetches and pins the exact public commit returned by `publish-mirror`, rather than
merging into the detached checkout. The wrapper prints both private→public mapping
and the preceding revision. `/var/lib/baromoon-deploy/last-release.json` records the
last attempt/recovery (revision IDs, status and UTC timestamp only). Keep the mapping
and command in the private handoff as well; that state file is not an audit history.

Tests exercise real disposable Git repositories for forward → rollback → forward,
failed health/restart recovery, interruption, rollback failure, stale preflight,
private/non-public sources, dependency mismatch, and preservation of runtime files.
Service calls/HTTP are mocked in those drills: this is **not a live outage drill**.
A host/SSH/disk failure can still require operator intervention; do not retry
blindly. No DNS rollback or static fallback has been revalidated.

`publish-mirror --prepare NEW_DIR` now makes the exact sanitized HEAD tree without
network access. It retains the existing exclusions/scrubbing and rejects tracked
runtime data/non-example profiles. Public-history isolation, dotfile removal and
no-op publication are tested using a local synthetic public repo. Failed commits
are no longer treated as successful no-ops; temporary clone cleanup is automatic.

Pre-cutover read-only verification: public `b399628`, no tracked edits, untracked
`venv/` retained; two gunicorn workers × four threads, loopback bind, 120-second
legacy timeout, unchanged 15-minute warmer. Six pinned dependencies match. Caddy's
**active configuration** has no access/body logging or extra trusted proxy hops;
gunicorn uses its default access format, not request bodies. A loopback-only
one-hop `ProxyFix` now prevents the new API's per-client quotas from collapsing
into a single Caddy-IP bucket; direct external peers cannot supply trusted headers.

**Cutover choice:** retain all existing legacy routes/APIs/CLI commands and the
warmer timer/service for compatibility. Its `/` hits become cheap form requests;
its `/report` and `/outlook` work remains. Do not claim a reduced overall legacy
workload/cost. No provider, hosting plan, dependencies, paid service, or static
snapshot change. Existing browser vault/settings stay intact; no data migration.
The historical ~$6/month estimate is not a newly audited invoice total.

Worktree verification: **374 offline Python tests, 20 window JS scenarios, eight
legacy JS scenarios and real Chromium acceptance**, including v3→v4 worker update,
old-cache purge, no home/API caching, offline behavior and saved-data preservation.
Sanitized-tree and initial production acceptance subsequently passed as recorded
above. Preparation tests themselves did not touch production services.

## Prior release preflight — 2026-10-23

- Reviewed reset checkpoint **`f69f7d8`** and documentation/preflight checkpoint
  **`fa6387f`** are pushed to private `SRMillerick/fishwitch-archive`.
- **Sean confirmed** the weather-service/commercial-use and astronomy-library
  permissions **“are established at the moment.”** Treat them as established for
  the current deployment on his confirmation, not as independently verified legal
  conclusions. Do not restart those as unresolved blockers or infer new purchases.
  Exact license/plan terms were not supplied in this exchange.
- Public main and deployed source remain **`b399628`**, mirror of archive
  `f2353a4`. The app and warmer timer are active; HTTPS returns 200 on the old
  homepage. All six pinned runtime versions match local versions. The production
  tree has no tracked edits; preserve its untracked `venv/`.
- An unpublished archive of the reset, with `publish-mirror` exclusions and lake
  scrubbing applied, passes 347 offline Python tests, 20 window JS scenarios,
  eight legacy JS scenarios and real Chromium acceptance. Internal files/private
  lake fields were verified absent. This is not a new-core production audit.
- **Next: complete technical release readiness and execute the requested deployment:**
  verify existing operating settings, legacy route/job cutover, concrete rollback
  procedure and production privacy/performance acceptance. Do not silently retire
  compatibility surfaces, change providers, or authorize new spending.
- Sean requested a handoff at 73.5% context after confirming permissions. This
  closeout is documentation only; no application tests were rerun, no public
  mirror/static snapshot was published and no service/deployment was changed.
  Resume from `HANDOFF.md` in a fresh session; the existing reset, not an unfinished
  personal-reading engine or new agent infrastructure, is the deployment scope.

## Routine checkpoint and release order

1. Review the full change set, including new files; run the relevant checks.
2. Commit a coherent slice and push `origin main` to the **private archive**.
   Verify the remote checkpoint; do not force-push or include real personal data.
3. Before a release, record the currently deployed **public** revision, validate
   the sanitized release tree and settle the gates above. Record the resulting
   private→public revision mapping after publication.
4. Use `./deploy/deploy.sh` only for an authorized, ready release. It publishes the
   clean mirror, fetches/pins that exact public revision on the VPS and restarts
   only `baromoon`, with automatic health-check recovery.
5. Verify HTTPS, expected page/API behavior, versions, privacy/error states and
   existing-client/service-worker behavior. Record results before further work.

Use the pinned rollback procedure above, not a private-history push or manual
SSH pull. A private Git checkpoint alone is not production rollback. The old
DNS/static-snapshot fallback is historical and is not the tested release path.

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
./deploy/deploy.sh          # sanitized mirror, public fetch/pin, restart + health gates
```

The VPS tracks the PUBLIC repo (clean mirror) — never the private archive.

Traffic and monetization telemetry live on the VPS under `/srv/fishwitch/logs/` and are read
from the dev box over ssh: `fishwitch stats --remote` (page views) and `fishwitch clicks --remote`
(outbound clicks). Plain `stats`/`clicks` read the local dev log.

## 5. Post-launch checklist

- [ ] https://baromoon.com renders the intended new window form, with no calculation on GET
- [ ] Synthetic API calculation and explicit error/degraded states pass; personal responses are `no-store`
- [ ] Installed-client/service-worker behavior and the documented rollback procedure are verified
- [ ] /privacy /disclosure /contact remain live while legacy affiliate routes are retained (Associates requirement)
- [ ] Porkbun email forwarding: hello@baromoon.com → Sean
- [ ] Apply: Amazon Associates (needs the live site + contact email)
- [ ] Apply: Tackle Warehouse affiliate (parallel)
- [ ] Optional: an uptime pinger (UptimeRobot free) on /
- [ ] Home-laptop service can stay as the "local mode" instance (FISHWITCH_LOCAL=1 there, /review live) — the VPS runs public-safe only

## Personal-data boundary

Saved profiles remain in the browser vault; the local logbook and LOCAL-gated
review panel must not be published. **Birth details do reach the server in
transient POST bodies for personal calculations.** Do not claim that the VPS
never sees them or that compromise cannot expose an in-flight request.

Personal requests/results must not be intentionally retained, placed in shared
caches or request URLs, or recorded by body/error logging. Verify application,
proxy, service and telemetry behavior as part of release preflight; source-level
checks alone are not a production privacy audit.
