#!/usr/bin/env bash
# Only sanctioned release/rollback entry point. Never publishes private history.
set -euo pipefail
DIR="$(dirname "$(readlink -f "$0")")/.."
cd "$DIR"

MODE=deploy
TARGET=
case "${1:-}" in
  '') [[ $# == 0 ]] || exit 2 ;;
  --check) [[ $# == 1 ]] || exit 2; MODE=check ;;
  --rollback) [[ $# == 2 && $2 =~ ^[0-9a-f]{40}$ ]] || {
    echo 'Use --rollback FULL_PUBLIC_COMMIT_ID' >&2; exit 2;
  }; MODE=rollback; TARGET=$2 ;;
  --help) echo 'Usage: ./deploy/deploy.sh [--check | --rollback FULL_PUBLIC_COMMIT_ID]'; exit 0 ;;
  *) echo 'Unknown option; use --help' >&2; exit 2 ;;
esac
HOST="${BAROMOON_HOST:-root@$(<deploy/host.txt)}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# This happens BEFORE public publication, and changes no production files/services.
"${SSH[@]}" python3 - check < deploy/release.py > "$WORK/before.json"
PREVIOUS=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["revision"])' "$WORK/before.json")
[[ $PREVIOUS =~ ^[0-9a-f]{40}$ ]] || exit 1
echo "Previous deployed public revision: $PREVIOUS"
if [[ $MODE == check ]]; then
  echo 'Read-only production Git preflight passed. No publication or restart.'
  exit 0
fi

if [[ $MODE == deploy ]]; then
  [[ $(git remote get-url origin) == git@github.com:SRMillerick/fishwitch-archive.git ]] || {
    echo 'Development origin must be the private archive' >&2; exit 1;
  }
  [[ $(git branch --show-current) == main && -z $(git status --porcelain) ]] || {
    echo 'Review/commit all tracked and untracked changes on main before deployment' >&2; exit 1;
  }
  SOURCE=$(git rev-parse HEAD)
  REMOTE=$(git ls-remote origin refs/heads/main | awk '{print $1}')
  [[ $SOURCE == "$REMOTE" ]] || { echo 'Push and verify the private checkpoint first' >&2; exit 1; }
  echo '→ Publishing sanitized public mirror…'
  ./publish-mirror --revision-file "$WORK/public-revision"
  TARGET=$(<"$WORK/public-revision")
  [[ $TARGET =~ ^[0-9a-f]{40}$ ]] || exit 1
  echo "Release mapping: archive@$SOURCE → public@$TARGET"
else
  echo "→ Pinned public rollback to $TARGET (no mirror publication)…"
fi

# The streamed helper works even if the pinned old release predates this tooling.
# Fetch + detached checkout pins public code/assets; venv and runtime data stay put.
"${SSH[@]}" python3 - apply "$TARGET" "$PREVIOUS" < deploy/release.py

echo '→ Checking public HTTPS…'
if ! python3 deploy/https_check.py "$TARGET" "$([[ $MODE == deploy ]] && echo window || echo any)"; then
  echo "HTTPS acceptance failed; restoring $PREVIOUS through the same release path" >&2
  "${SSH[@]}" python3 - apply "$PREVIOUS" "$TARGET" < deploy/release.py
  python3 deploy/https_check.py "$PREVIOUS" any || {
    echo 'RESTORED CODE, BUT HTTPS STILL FAILS; operator intervention required' >&2; exit 1;
  }
  exit 1
fi
if [[ $MODE == deploy ]]; then
  echo '→ Pinging IndexNow…'
  ./deploy/indexnow.sh || echo '⚠ IndexNow ping failed (the site is still live)'
fi
echo "Healthy public revision: $TARGET"
echo "Rollback command: ./deploy/deploy.sh --rollback $PREVIOUS"
