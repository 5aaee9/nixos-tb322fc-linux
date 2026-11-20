"""Exercise rollback retention and the exact entry identity without device access."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "boot_generations", Path(__file__).resolve().parents[1] / "tools/install-boot-generations.py")
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)
SYSTEM = "/nix/store/" + "a" * 32 + "-nixos-system-Limestone-test"


class SnapshotRetention(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "boot"
        (self.base / "snapshots").mkdir(parents=True)
        self.roots = Path(self.temp.name) / "gcroots"
        self.roots.mkdir()
        self.paths = []
        for number in (1, 2, 3):
            data = str(number).encode()
            checksum = hashlib.sha256(data).hexdigest()
            path = self.base / "snapshots" / f"{number}-{checksum}"
            path.mkdir()
            (path / "esp.img").write_bytes(data)
            (path / "esp.sha256").write_text(f"{checksum}  esp.img\n")
            (path / "manifest.json").write_text(json.dumps({
                "schema": 1, "default": number, "image_sha256": checksum,
                "image_bytes": len(data), "generations": {str(number): {"system": SYSTEM}},
            }))
            roots = self.roots / path.name
            roots.mkdir()
            (roots / str(number)).symlink_to(SYSTEM)
            self.paths.append(path)
        (self.base / "current").symlink_to(self.paths[2])
        (self.base / "previous").symlink_to(self.paths[1])

    def test_keeps_current_previous_and_their_gc_roots(self):
        boot.prune_snapshots(self.base, self.roots)
        self.assertEqual(set((self.base / "snapshots").iterdir()), set(self.paths[1:]))
        self.assertEqual({p.name for p in self.roots.iterdir()}, {p.name for p in self.paths[1:]})

    def test_corrupt_current_retains_all_rollback_data(self):
        (self.paths[2] / "esp.img").write_bytes(b"broken")
        with self.assertRaises(ValueError):
            boot.prune_snapshots(self.base, self.roots)
        self.assertTrue(all(p.is_dir() for p in self.paths))
        self.assertEqual(len(list(self.roots.iterdir())), 3)

    def test_unknown_file_is_never_deleted(self):
        (self.paths[0] / "owner-file").write_text("preserve")
        with self.assertRaises(ValueError):
            boot.prune_snapshots(self.base, self.roots)
        self.assertTrue(all(p.is_dir() for p in self.paths))
        self.assertEqual((self.paths[0] / "owner-file").read_text(), "preserve")

    def test_gc_root_substitution_stops_before_deletion(self):
        link = self.roots / self.paths[0].name / "1"
        link.unlink()
        link.symlink_to("/tmp/unrelated-system")
        with self.assertRaises(ValueError):
            boot.prune_snapshots(self.base, self.roots)
        self.assertTrue(all(p.is_dir() for p in self.paths))

    def test_missing_retained_gc_root_preserves_older_rollback(self):
        (self.roots / self.paths[2].name / "3").unlink()
        with self.assertRaises(ValueError):
            boot.prune_snapshots(self.base, self.roots)
        self.assertTrue(all(p.is_dir() for p in self.paths))

    def test_broken_retained_pointer_stops_before_deletion(self):
        (self.base / "previous").unlink()
        (self.base / "previous").symlink_to(self.base / "missing")
        with self.assertRaises(FileNotFoundError):
            boot.prune_snapshots(self.base, self.roots)
        self.assertTrue(all(p.is_dir() for p in self.paths))


class EntryIdentity(unittest.TestCase):
    def test_exact_system_replaces_stale_cmdline(self):
        value = boot.options("root=PARTLABEL=rootfs rdinit=/init efi=noruntime "
                             "init=/old y700.generation=1 panic=0", SYSTEM, 17, False)
        self.assertIn(f"init={SYSTEM}/init", value.split())
        self.assertIn("y700.generation=17", value.split())
        self.assertNotIn("efi=noruntime", value)
        self.assertNotIn("init=/old", value)
        self.assertNotIn("y700.usb-debug=1", value)

    def test_newc_entry_identity(self):
        archive = boot.identity_archive(SYSTEM, 17)
        offset, entries = 0, {}
        while True:
            self.assertEqual(archive[offset:offset + 6], b"070701")
            fields = [int(archive[offset + 6 + n * 8:offset + 14 + n * 8], 16)
                      for n in range(13)]
            start = offset + 110
            name = archive[start:start + fields[11] - 1].decode()
            start = (start + fields[11] + 3) & ~3
            data = archive[start:start + fields[6]]
            offset = (start + fields[6] + 3) & ~3
            if name == "TRAILER!!!":
                break
            entries[name] = data
        self.assertEqual(entries, {
            "etc/y700-efi-system": (SYSTEM + "\n").encode(),
            "etc/y700-efi-generation": b"17\n",
        })
        self.assertEqual(len(archive) % 512, 0)


if __name__ == "__main__":
    unittest.main()
