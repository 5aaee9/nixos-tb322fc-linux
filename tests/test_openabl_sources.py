import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("openabl_sources", PROJECT / "tools/verify-openabl-sources.py")
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)


class OpenAblSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "source"
        self.repo.mkdir()
        self.git("init", "-q")
        (self.repo / "source.c").write_text("int value = 1;\n")
        (self.repo / "other.c").write_text("int other = 1;\n")
        (self.repo / ".gitignore").write_text("*.ignored.c\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "fixture")
        self.pin = self.git("rev-parse", "HEAD").decode().strip()
        self.expected = sources.pinned_files(self.repo, self.pin)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args],
                                       stderr=subprocess.STDOUT)

    def test_clean_pinned_tree(self):
        report = sources.check_files(self.repo, self.expected)
        self.assertEqual(report["files"], 3)

    def test_pinned_eol_attribute_is_applied(self):
        (self.repo / ".gitattributes").write_text("windows.txt text eol=crlf\n")
        (self.repo / "windows.txt").write_bytes(b"line\r\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "line endings")
        pin = self.git("rev-parse", "HEAD").decode().strip()
        expected = sources.pinned_files(self.repo, pin)
        self.assertEqual(expected["windows.txt"][1], b"line\r\n")
        sources.check_files(self.repo, expected)
        (self.repo / ".gitattributes").write_text("windows.txt text eol=lf\n")
        with self.assertRaisesRegex(ValueError, "Unreviewed source content"):
            sources.check_files(self.repo, expected)

    def test_unreviewed_tracked_change_even_if_assume_unchanged(self):
        self.git("update-index", "--assume-unchanged", "other.c")
        (self.repo / "other.c").write_text("int other = 2;\n")
        self.assertEqual(self.git("diff", "HEAD"), b"")
        with self.assertRaisesRegex(ValueError, "Unreviewed source content"):
            sources.check_files(self.repo, self.expected)

    def test_ignored_source_addition_is_rejected(self):
        (self.repo / "extra.ignored.c").write_text("int surprise;\n")
        with self.assertRaisesRegex(ValueError, "Unreviewed extra source"):
            sources.check_files(self.repo, self.expected)

    def test_staged_source_addition_is_rejected(self):
        (self.repo / "extra.c").write_text("int staged_surprise;\n")
        self.git("add", "extra.c")
        self.assertEqual(self.git("ls-files", "--others"), b"")
        with self.assertRaisesRegex(ValueError, "Unreviewed extra source"):
            sources.check_files(self.repo, self.expected)

    def test_patch_reconstruction_does_not_modify_source(self):
        patch = Path(self.temp.name) / "reviewed.patch"
        patch.write_text(
            "diff --git a/source.c b/source.c\n"
            "--- a/source.c\n+++ b/source.c\n"
            "@@ -1 +1 @@\n-int value = 1;\n+int value = 2;\n")
        expected = sources.apply_expected_patches(self.expected, [patch])
        self.assertEqual((self.repo / "source.c").read_text(), "int value = 1;\n")
        with self.assertRaisesRegex(ValueError, "Unreviewed source content"):
            sources.check_files(self.repo, expected)
        (self.repo / "source.c").write_bytes(expected["source.c"][1])
        sources.check_files(self.repo, expected)
        (self.repo / "other.c").write_text("int other = 3;\n")
        with self.assertRaisesRegex(ValueError, "Unreviewed source content"):
            sources.check_files(self.repo, expected)

    def test_only_exact_config_alternatives_are_accepted(self):
        alternatives = {"source.c": (b"int value = 1;\n", b"int value = 2;\n")}
        before = sources.check_files(self.repo, self.expected, alternatives=alternatives)
        (self.repo / "source.c").write_text("int value = 2;\n")
        after = sources.check_files(self.repo, self.expected, alternatives=alternatives)
        self.assertEqual(before["canonical_sha256"], after["canonical_sha256"])
        (self.repo / "source.c").write_text("int value = 3;\n")
        with self.assertRaisesRegex(ValueError, "Unreviewed source content"):
            sources.check_files(self.repo, self.expected, alternatives=alternatives)

    def test_symlink_substitution_is_rejected(self):
        (self.repo / "source.c").unlink()
        (self.repo / "source.c").symlink_to("other.c")
        with self.assertRaisesRegex(ValueError, "Source must be regular"):
            sources.check_files(self.repo, self.expected)

    def test_only_known_edk2_generated_files_are_excluded(self):
        self.assertTrue(sources.generated_extra(sources.PREBUILT, "build/edk2"))
        self.assertTrue(sources.generated_extra("build_modulepkg.log", "build/edk2"))
        self.assertTrue(sources.generated_extra("obj/ABL_OBJ/Build/file.obj", "build/edk2"))
        self.assertFalse(sources.generated_extra("QcomModulePkg/Prebuilt/extra.efi", "build/edk2"))
        self.assertFalse(sources.generated_extra("QcomModulePkg/Library/extra.c", "build/edk2"))
        self.assertFalse(sources.generated_extra("Conf/tools_def.txt", "build/edk2"))


if __name__ == "__main__":
    unittest.main()
