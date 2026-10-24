"""Exercise the actual mirror script against synthetic local repositories only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class MirrorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.git(self.source, "init", "-q", "-b", "main")
        shutil.copy2(ROOT / "publish-mirror", self.source / "publish-mirror")
        self.put("config/lakes.json", json.dumps({"fixture": dict(name="Public water", lore="private",
                                                                 access="private", structure="private")}))
        self.put("config/profiles/example.json", '{"name":"Synthetic"}')
        for name in ("HANDOFF.md", "STATE.md", "START.md", "ASSOCIATES.md", "SEO.md", "COVERAGE.md",
                     "baromoon_prelim_plan.md", "PRODUCT_RESET.md", "reports/fixture.txt",
                     "submissions/fixture.txt", "config/candidates/fixture.json"):
            self.put(name, "synthetic internal sentinel")
        self.put("README.md", "Public fixture")
        self.private_revision = self.commit(self.source)
        self.env = dict(os.environ, BAROMOON_PYTHON=sys.executable, GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=os.devnull)

    def put(self, name, text):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(self, root, *args):
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()

    def commit(self, root):
        self.git(root, "add", "-A")
        self.git(root, "-c", "user.name=fixture", "-c", "user.email=fixture@localhost",
                 "commit", "-qm", "synthetic private fixture")
        return self.git(root, "rev-parse", "HEAD")

    def run_mirror(self, *args):
        return subprocess.run([str(self.source / "publish-mirror"), *map(str, args)], cwd=self.source,
                              env=self.env, capture_output=True, text=True, timeout=15)

    def test_prepare_strips_internal_files_and_private_lake_fields(self):
        tree = self.base / "tree"
        result = self.run_mirror("--prepare", tree)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((tree / "config/lakes.json").read_text()),
                         {"fixture": {"name": "Public water"}})
        for path in tree.rglob("*"):
            if path.is_file():
                self.assertNotIn("synthetic internal sentinel", path.read_text())
        self.assertIn(self.private_revision[:7], (tree / "PUBLIC-NOTES.md").read_text())
        self.assertFalse((tree / ".git").exists())

    def test_prepare_refuses_existing_destination_without_deleting_it(self):
        tree = self.base / "tree"
        tree.mkdir()
        (tree / "keep").write_text("preserve")
        self.assertNotEqual(self.run_mirror("--prepare", tree).returncode, 0)
        self.assertEqual((tree / "keep").read_text(), "preserve")

    def test_tracked_runtime_files_fail_closed(self):
        self.put("logs/fixture.jsonl", "synthetic must not publish")
        self.commit(self.source)
        result = self.run_mirror("--prepare", self.base / "tree")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing private/runtime path", result.stderr)

    def test_non_example_profile_fails_closed(self):
        self.put("config/profiles/other.json", "synthetic must not publish")
        self.commit(self.source)
        result = self.run_mirror("--prepare", self.base / "tree")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing non-example profiles", result.stderr)

    def test_dirty_publication_is_refused_before_any_network(self):
        self.put("README.md", "uncommitted change")
        result = self.run_mirror()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Review and commit", result.stderr)

    def test_publication_keeps_only_public_history_and_removes_stale_dotfiles(self):
        public = self.base / "public-source"
        public.mkdir()
        self.git(public, "init", "-q", "-b", "main")
        (public / ".obsolete").write_text("old public file")
        old_public = self.commit(public)
        remote = self.base / "public.git"
        self.git(self.base, "clone", "-q", "--bare", str(public), str(remote))
        # Git's URL rewrite directs the script's exact sanctioned public URL to
        # this disposable local bare repo. No SSH/network command is executed.
        self.env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0=f"url.{remote}.insteadOf",
                        GIT_CONFIG_VALUE_0="git@github.com:SRMillerick/fishwitch.git")
        revision_file = self.base / "revision"
        result = self.run_mirror("--revision-file", revision_file)
        self.assertEqual(result.returncode, 0, result.stderr)
        public_revision = self.git(remote, "rev-parse", "main")
        self.assertEqual(revision_file.read_text().strip(), public_revision)
        self.assertEqual(self.git(remote, "rev-parse", "main^"), old_public)
        self.assertEqual(self.git(remote, "rev-list", "--count", "main"), "2")
        names = self.git(remote, "ls-tree", "-r", "--name-only", "main").splitlines()
        self.assertNotIn(".obsolete", names)
        self.assertNotIn("HANDOFF.md", names)
        exists = subprocess.run(["git", "cat-file", "-e", self.private_revision], cwd=remote,
                                capture_output=True).returncode
        self.assertNotEqual(exists, 0, "Private history must not reach the public object store")
        # Same source = clean no-op, not a spurious commit/failure.
        self.assertEqual(self.run_mirror("--revision-file", revision_file).returncode, 0)
        self.assertEqual(self.git(remote, "rev-parse", "main"), public_revision)


if __name__ == "__main__":
    unittest.main()
