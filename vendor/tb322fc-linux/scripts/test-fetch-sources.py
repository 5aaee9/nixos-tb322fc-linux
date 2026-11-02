#!/usr/bin/env python3
"""Exercise source fetching against a local Git fixture without network access."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("fetch-sources.py")


class SourceFetchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="source-fetch-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.upstream = self.root / "upstream"
        self.project = self.root / "project"
        (self.project / "scripts").mkdir(parents=True)
        (self.project / "patches").mkdir()
        shutil.copyfile(SCRIPT, self.project / "scripts" / SCRIPT.name)
        self.git(self.root, "init", "--quiet", str(self.upstream))
        commits = []
        for text in ("base\n", "base\nfirst\n", "base\nfirst\nsecond\n"):
            (self.upstream / "device.txt").write_text(text)
            self.git(self.upstream, "add", "device.txt")
            self.git(self.upstream, "-c", "user.name=Source fixture",
                     "-c", "user.email=fixture@example.invalid",
                     "-c", "commit.gpgsign=false",
                     "commit", "--quiet", "-m", "Update fixture")
            commits.append(self.git(self.upstream, "rev-parse", "HEAD"))
        for number, (before, after) in enumerate(zip(commits, commits[1:]), 1):
            patch = self.git(self.upstream, "diff", "--full-index", before, after)
            (self.project / "patches" / f"{number}.patch").write_text(patch + "\n")
        self.base, self.first, self.final = commits
        self.source = {
            "url": str(self.upstream),
            "commit": self.base,
            "base_tree": self.tree(self.base),
            "patches": ["patches/1.patch", "patches/2.patch"],
            "tree": self.tree(self.final),
        }

    @staticmethod
    def git(directory, *args):
        return subprocess.check_output(
            ["git", "-C", str(directory), *args], text=True,
            stderr=subprocess.PIPE).strip()

    def tree(self, commit):
        return self.git(self.upstream, "rev-parse", commit + "^{tree}")

    def fetch(self):
        (self.project / "sources.json").write_text(
            json.dumps({"kernel": self.source}))
        return subprocess.run(
            [sys.executable, str(self.project / "scripts" / SCRIPT.name), "kernel"],
            text=True, capture_output=True, timeout=30)

    def test_ordered_series_reproduces_expected_tree(self):
        result = self.fetch()
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.project / "sources/kernel"
        self.assertEqual(self.git(target, "rev-parse", "HEAD"), self.base)
        self.assertEqual(self.git(target, "write-tree"), self.tree(self.final))
        self.assertEqual(self.git(target, "diff", "--exit-code"), "")
        self.assertEqual((target / "device.txt").read_text(),
                         "base\nfirst\nsecond\n")

    def test_wrong_order_fails(self):
        self.source["patches"].reverse()
        result = self.fetch()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Verified kernel", result.stdout)

    def test_wrong_upstream_tree_fails_before_applying(self):
        self.source["base_tree"] = self.tree(self.first)
        result = self.fetch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upstream tree does not match", result.stderr)
        self.assertEqual(
            (self.project / "sources/kernel/device.txt").read_text(), "base\n")

    def test_wrong_result_tree_fails(self):
        self.source["tree"] = self.tree(self.base)
        result = self.fetch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source tree does not match", result.stderr)
        self.assertNotIn("Verified kernel", result.stdout)

    def test_legacy_single_patch(self):
        del self.source["patches"]
        del self.source["base_tree"]
        self.source["patch"] = "patches/1.patch"
        self.source["tree"] = self.tree(self.first)
        result = self.fetch()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_checkout_is_preserved(self):
        target = self.project / "sources/kernel"
        target.mkdir(parents=True)
        marker = target / "keep.txt"
        marker.write_text("local work\n")
        result = self.fetch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(marker.read_text(), "local work\n")
        self.assertEqual(list(target.iterdir()), [marker])

    def test_ambiguous_patch_fields_are_rejected(self):
        self.source["patch"] = "patches/1.patch"
        result = self.fetch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("use either patch or patches", result.stderr)
        self.assertFalse((self.project / "sources").exists())


if __name__ == "__main__":
    unittest.main()
