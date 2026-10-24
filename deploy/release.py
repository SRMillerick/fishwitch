#!/usr/bin/env python3
"""VPS half of deploy.sh, streamed over SSH; stdlib only, including on rollback.

Only public-origin commits are accepted. No dependency installation, data cleanup,
service-unit changes, or static-site publication. Tests use disposable Git repos.
"""
import fcntl
import json
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

PUBLIC_ORIGINS = (
    "https://github.com/SRMillerick/fishwitch.git",
    "git@github.com:SRMillerick/fishwitch.git",
)


class ReleaseError(RuntimeError):
    pass


class Release:
    def __init__(self, root=Path("/srv/fishwitch"), origins=PUBLIC_ORIGINS,
                 state=Path("/var/lib/baromoon-deploy/last-release.json")):
        self.root, self.origins, self.state = Path(root), origins, Path(state)

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        if result.returncode:
            # Do not echo arbitrary filenames, URLs, or local data into release logs.
            raise ReleaseError("Git command failed: " + args[0])
        return result.stdout.strip()

    def inspect(self):
        if self.git("remote", "get-url", "origin") not in self.origins:
            raise ReleaseError("Production origin is not the sanctioned public mirror")
        if self.git("status", "--porcelain", "--untracked-files=no"):
            raise ReleaseError("Production has tracked changes; preserve and review them")
        if any((self.root / ".git" / p).exists() for p in
               ("MERGE_HEAD", "CHERRY_PICK_HEAD", "rebase-merge", "rebase-apply")):
            raise ReleaseError("Production has an unfinished Git operation")
        return {"revision": self.git("rev-parse", "HEAD")}

    def restart(self):
        subprocess.run(["systemctl", "restart", "baromoon"], check=True, timeout=90,
                       stdout=subprocess.DEVNULL)

    def health(self, revision):
        # New homepage is calculation-free. Older rollback revisions may have a
        # cold legacy homepage, so allow its existing 120-second service budget.
        is_window = 'id="window-form"' in self.git(
            "show", revision + ":web/templates/window.html") if self.has_window(revision) else False
        timeout = 5 if is_window else 125
        for attempt in range(6):
            try:
                subprocess.run(["systemctl", "is-active", "--quiet", "baromoon"],
                               check=True, timeout=10)
                with urlopen("http://127.0.0.1:7700/?warm=1", timeout=timeout) as response:
                    html = response.read(2_000_000).decode("utf-8")
                    marker = 'id="window-form"' if is_window else "baromoon"
                    if response.status == 200 and marker in html:
                        return
            except Exception:
                pass
            time.sleep(2)
        raise ReleaseError("Local HTTP/service health check failed")

    def has_window(self, revision):
        return "web/templates/window.html" in self.git("ls-tree", "-r", "--name-only", revision).splitlines()

    def checkout(self, revision):
        # --no-overwrite-ignore also protects ignored runtime paths on collision.
        # Detached HEAD pins the release; no public or local branch is rewritten.
        self.git("checkout", "--quiet", "--no-overwrite-ignore", "--detach", revision)

    def record(self, previous, target, status):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        data = dict(previous=previous, target=target, status=status,
                    recorded_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        temporary = self.state.with_suffix(".tmp")
        temporary.write_text(json.dumps(data) + "\n")
        temporary.replace(self.state)

    def apply(self, target, expected_previous):
        if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (target, expected_previous)):
            raise ReleaseError("Use full 40-character public commit IDs")
        previous = self.inspect()["revision"]
        if previous != expected_previous:
            raise ReleaseError("Production changed since preflight; recheck before releasing")
        # Always fetch the PUBLIC branch, never a caller-supplied remote/refspec.
        self.git("fetch", "--quiet", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main")
        self.git("merge-base", "--is-ancestor", target, "refs/remotes/origin/main")
        if self.git("show", previous + ":requirements.txt") != self.git("show", target + ":requirements.txt"):
            raise ReleaseError("Dependencies changed; this code-only rollback path cannot safely migrate the venv")
        self.record(previous, target, "starting")
        switched = False
        try:
            self.checkout(target)
            switched = True
            self.restart()
            self.health(target)
            self.record(previous, target, "healthy")
        except BaseException:
            if switched:
                try:
                    self.checkout(previous)
                    self.restart()
                    self.health(previous)
                    self.record(previous, target, "rolled-back")
                except BaseException as rollback_error:
                    self.record(previous, target, "rollback-failed")
                    raise ReleaseError("AUTOMATIC ROLLBACK FAILED; operator intervention required") from rollback_error
                raise ReleaseError("Release failed; previous revision restored and health checked") from None
            self.record(previous, target, "checkout-refused")
            raise
        return dict(previous=previous, revision=target, status="healthy")


def interrupted(signum, frame):
    raise InterruptedError("Release interrupted")


def main(args):
    release = Release()
    if args == ["check"]:
        print(json.dumps(release.inspect()))
        return
    if len(args) != 3 or args[0] != "apply":
        raise ReleaseError("Expected check, or apply TARGET EXPECTED_PREVIOUS")
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    # Serializes sanctioned deploy/rollback operations on this host. The expected
    # revision guard also catches changes between local preflight and this lock.
    with open("/run/lock/baromoon-deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(release.apply(args[1], args[2])))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as error:
        print("Release stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
