"""Release/rollback drills: real disposable Git history; fake service and HTTP.

No SSH, public publication, production restart, or dependency installation.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release", ROOT / "deploy/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source, self.remote, self.root = [self.base / p for p in ("source", "public.git", "fishwitch")]
        self.source.mkdir()
        self.git(self.source, "init", "-q", "-b", "main")
        (self.source / "requirements.txt").write_text("Flask==3.1.3\n")
        (self.source / ".gitignore").write_text("logs/\nvenv/\n")
        (self.source / "app.txt").write_text("legacy\n")
        self.old = self.commit()
        (self.source / "app.txt").write_text("window\n")
        self.new = self.commit()
        self.git(self.base, "clone", "-q", "--bare", str(self.source), str(self.remote))
        self.git(self.base, "clone", "-q", str(self.remote), str(self.root))
        self.git(self.root, "checkout", "-q", "--detach", self.old)
        for name in ("venv/keep", "logs/keep", "untracked-keep"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"synthetic runtime sentinel\x00")
        self.deploy = release.Release(self.root, (str(self.remote),), self.base / "last.json")
        self.deploy.restart = mock.Mock()
        self.deploy.health = mock.Mock()

    def git(self, root, *args):
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def commit(self):
        self.git(self.source, "add", "-A")
        self.git(self.source, "-c", "user.name=fixture", "-c", "user.email=fixture@localhost",
                 "commit", "-qm", "synthetic release")
        return self.git(self.source, "rev-parse", "HEAD")

    def publish(self):
        target = self.commit()
        self.git(self.source, "push", "-q", str(self.remote), "main")
        return target

    def assert_preserved(self):
        for name in ("venv/keep", "logs/keep", "untracked-keep"):
            self.assertEqual((self.root / name).read_bytes(), b"synthetic runtime sentinel\x00")

    def test_forward_rollback_forward_pins_code_and_preserves_runtime(self):
        for before, target in ((self.old, self.new), (self.new, self.old), (self.old, self.new)):
            result = self.deploy.apply(target, before)
            self.assertEqual(result["revision"], target)
            self.assertEqual(self.deploy.inspect()["revision"], target)
            self.assertEqual(self.git(self.root, "branch", "--show-current"), "")
            self.assertEqual(json.loads(self.deploy.state.read_text())["status"], "healthy")
            self.assert_preserved()
        self.assertEqual(self.deploy.restart.call_count, 3)

    def test_failed_health_restores_previous_revision_and_checks_it(self):
        self.deploy.health.side_effect = [release.ReleaseError("fixture down"), None]
        with self.assertRaisesRegex(release.ReleaseError, "previous revision restored"):
            self.deploy.apply(self.new, self.old)
        self.assertEqual(self.deploy.inspect()["revision"], self.old)
        self.assertEqual(self.deploy.health.call_args_list, [mock.call(self.new), mock.call(self.old)])
        self.assertEqual(json.loads(self.deploy.state.read_text())["status"], "rolled-back")
        self.assert_preserved()

    def test_failed_restart_restores_previous_revision(self):
        self.deploy.restart.side_effect = [RuntimeError("fixture restart failed"), None]
        with self.assertRaisesRegex(release.ReleaseError, "previous revision restored"):
            self.deploy.apply(self.new, self.old)
        self.assertEqual(self.deploy.inspect()["revision"], self.old)
        self.deploy.health.assert_called_once_with(self.old)

    def test_failed_rollback_is_not_reported_as_success(self):
        self.deploy.health.side_effect = RuntimeError("fixture down")
        with self.assertRaisesRegex(release.ReleaseError, "AUTOMATIC ROLLBACK FAILED"):
            self.deploy.apply(self.new, self.old)
        self.assertEqual(json.loads(self.deploy.state.read_text())["status"], "rollback-failed")

    def test_interrupted_cutover_attempts_recovery(self):
        self.deploy.health.side_effect = [InterruptedError("fixture signal"), None]
        with self.assertRaisesRegex(release.ReleaseError, "previous revision restored"):
            self.deploy.apply(self.new, self.old)
        self.assertEqual(self.deploy.inspect()["revision"], self.old)

    def test_changed_revision_since_preflight_stops_before_restart(self):
        with self.assertRaisesRegex(release.ReleaseError, "changed since preflight"):
            self.deploy.apply(self.new, self.new)
        self.deploy.restart.assert_not_called()

    def test_dirty_tracked_file_is_preserved(self):
        (self.root / "app.txt").write_text("operator edit")
        with self.assertRaisesRegex(release.ReleaseError, "tracked changes"):
            self.deploy.apply(self.new, self.old)
        self.assertEqual((self.root / "app.txt").read_text(), "operator edit")
        self.deploy.restart.assert_not_called()

    def test_private_remote_is_refused(self):
        self.git(self.root, "remote", "set-url", "origin", "git@github.com:SRMillerick/fishwitch-archive.git")
        with self.assertRaisesRegex(release.ReleaseError, "sanctioned public mirror"):
            self.deploy.apply(self.new, self.old)
        self.deploy.restart.assert_not_called()

    def test_dependency_change_is_refused_without_touching_venv(self):
        (self.source / "requirements.txt").write_text("Flask==0.0.0\n")
        target = self.publish()
        with self.assertRaisesRegex(release.ReleaseError, "Dependencies changed"):
            self.deploy.apply(target, self.old)
        self.assertEqual(self.deploy.inspect()["revision"], self.old)
        self.deploy.restart.assert_not_called()
        self.assert_preserved()

    def test_non_public_commit_is_refused(self):
        (self.source / "app.txt").write_text("not published")
        target = self.commit()
        # Import an object locally, but do not put it on public main.
        self.git(self.root, "fetch", "-q", str(self.source), "main")
        with self.assertRaises(release.ReleaseError):
            self.deploy.apply(target, self.old)
        self.deploy.restart.assert_not_called()

    def test_short_or_injected_revisions_are_refused(self):
        for value in (self.new[:7], "main", "-f", self.new + ";echo nope"):
            with self.assertRaisesRegex(release.ReleaseError, "40-character"):
                self.deploy.apply(value, self.old)
        self.deploy.restart.assert_not_called()

    def test_ignored_runtime_collision_is_not_overwritten(self):
        (self.source / "venv").mkdir()
        (self.source / "venv/keep").write_text("bad tracked replacement")
        self.git(self.source, "add", "-f", "venv/keep")
        target = self.publish()
        with self.assertRaises(release.ReleaseError):
            self.deploy.apply(target, self.old)
        self.assertEqual(self.deploy.inspect()["revision"], self.old)
        self.deploy.restart.assert_not_called()
        self.assert_preserved()

    def test_untracked_runtime_collision_is_not_overwritten(self):
        (self.source / "untracked-keep").write_text("bad tracked replacement")
        target = self.publish()
        with self.assertRaises(release.ReleaseError):
            self.deploy.apply(target, self.old)
        self.deploy.restart.assert_not_called()
        self.assert_preserved()

    def test_read_only_check_does_not_write_state_or_restart(self):
        self.assertEqual(self.deploy.inspect(), {"revision": self.old})
        self.assertFalse(self.deploy.state.exists())
        self.deploy.restart.assert_not_called()

    def test_http_health_requires_service_and_expected_form(self):
        self.deploy.health = release.Release.health.__get__(self.deploy)
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'<form id="window-form">baromoon</form>'
        with mock.patch.object(self.deploy, "has_window", return_value=True), \
                mock.patch.object(self.deploy, "git", return_value='id="window-form"'), \
                mock.patch.object(release.subprocess, "run") as run, \
                mock.patch.object(release, "urlopen", return_value=response) as get:
            self.deploy.health(self.new)
            self.assertEqual(get.call_args.kwargs["timeout"], 5)
            self.assertIn("is-active", run.call_args.args[0])
        response.read.return_value = b"baromoon old homepage"
        with mock.patch.object(self.deploy, "has_window", return_value=True), \
                mock.patch.object(self.deploy, "git", return_value='id="window-form"'), \
                mock.patch.object(release.subprocess, "run"), \
                mock.patch.object(release, "urlopen", return_value=response), \
                mock.patch.object(release.time, "sleep"):
            with self.assertRaisesRegex(release.ReleaseError, "health check failed"):
                self.deploy.health(self.new)


class HttpsGateTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("https_check", ROOT / "deploy/https_check.py")
        self.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gate)
        self.response = mock.MagicMock()
        self.response.__enter__.return_value = self.response
        self.response.status = 200
        self.response.geturl.return_value = "https://baromoon.com/?warm=1"
        self.response.read.return_value = b'<form id="window-form">baromoon</form>'

    def test_https_window_contract_and_uncached_request(self):
        with mock.patch.object(self.gate, "urlopen", return_value=self.response) as get, \
                mock.patch("builtins.print"):
            self.assertTrue(self.gate.check("a" * 40, "window"))
            self.assertEqual(get.call_args.args[0].get_header("Cache-control"), "no-cache")
            self.assertTrue(get.call_args.args[0].full_url.startswith("https://baromoon.com/"))

    def test_old_homepage_fails_new_contract_but_supports_rollback(self):
        self.response.read.return_value = b"baromoon legacy"
        with mock.patch.object(self.gate, "urlopen", return_value=self.response), \
                mock.patch.object(self.gate.time, "sleep"), mock.patch("builtins.print"):
            self.assertFalse(self.gate.check("a" * 40, "window"))
            self.assertTrue(self.gate.check("a" * 40, "any"))

    def test_transport_failure_or_wrong_origin_fails_closed(self):
        with mock.patch.object(self.gate, "urlopen", side_effect=OSError("fixture offline")), \
                mock.patch.object(self.gate.time, "sleep"):
            self.assertFalse(self.gate.check("a" * 40, "window"))
        self.response.geturl.return_value = "http://baromoon.com/"
        with mock.patch.object(self.gate, "urlopen", return_value=self.response), \
                mock.patch.object(self.gate.time, "sleep"):
            self.assertFalse(self.gate.check("a" * 40, "window"))


if __name__ == "__main__":
    unittest.main()
