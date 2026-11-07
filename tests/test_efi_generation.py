import importlib.util
import gzip
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("esp", PROJECT / "tools/build-efi-esp.py")
esp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(esp)
gen = esp.generation
ram_spec = importlib.util.spec_from_file_location("ram_media", PROJECT / "tools/build-uefi-ramfs.py")
ram = importlib.util.module_from_spec(ram_spec)
ram_spec.loader.exec_module(ram)
SYSTEM = "/nix/store/" + "1" * 32 + "-nixos-system-y700-test"


class EfiGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def bundle(self, number=1):
        directory = self.directory / str(number)
        directory.mkdir()
        image = bytearray(256)
        image[:2] = b"MZ"
        struct.pack_into("<I", image, 0x3c, 64)
        image[64:68] = b"PE\0\0"
        struct.pack_into("<H", image, 68, 0xaa64)
        struct.pack_into("<H", image, 88, 0x20b)
        (directory / "linux.efi").write_bytes(image)
        (directory / "elden.dtb").write_bytes(b"\xd0\x0d\xfe\xedfixture")
        (directory / "initrd.gz").write_bytes(b"fixture-initrd")
        options = gen.command_line(SYSTEM, number)
        (directory / "options").write_text(options + "\n")
        (directory / "system-path").write_text(SYSTEM + "\n")
        (directory / "generation-number").write_text(str(number) + "\n")
        namespace = gen.esp_namespace(number, gen.sha(directory / "linux.efi"),
                                      gen.sha(directory / "initrd.gz"), gen.sha(directory / "elden.dtb"))
        bootspec = {
            "org.nixos.bootspec.v1": {
                "toplevel": SYSTEM, "init": SYSTEM + "/init", "system": "aarch64-linux",
                "kernelParams": options.split(), "kernel": f"/boot/{namespace}/linux.efi",
                "initrd": f"/boot/{namespace}/initrd.gz",
            },
            "org.y700.board.v1": {"dtb": f"/boot/{namespace}/elden.dtb", "generation": number},
        }
        (directory / "boot.json").write_text(json.dumps(bootspec))
        meta = {
            "schema": 1, "generation": number, "system": SYSTEM, "esp_namespace": namespace,
            "files": {name: gen.sha(directory / name) for name in esp.FILES},
            "kernel": {
                "kernel": json.loads((gen.VENDOR / "sources.json").read_text())["kernel"],
                "files": {"Image": gen.sha(directory / "linux.efi"),
                          "elden.dtb": gen.sha(directory / "elden.dtb")},
            },
            "firmware_manifest_sha256": gen.sha(gen.VENDOR / "firmware-tb322fc-prc.json"),
            "nixpkgs": json.loads((PROJECT / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"],
        }
        (directory / "metadata.json").write_text(json.dumps(meta))
        return directory, meta

    def test_exact_selection_options(self):
        options = gen.command_line(SYSTEM, 2, True).split()
        self.assertIn("y700.system=" + SYSTEM, options)
        self.assertIn("y700.generation=2", options)
        self.assertIn("rdinit=/init", options)
        self.assertIn("y700.usb-debug=1", options)
        self.assertNotIn("efi=noruntime", options)

    def test_rejects_injected_or_relative_system(self):
        for system in ("../../init", SYSTEM + " init=/bin/sh", SYSTEM + "\n", "/nix/store/../init"):
            with self.subTest(system=system), self.assertRaises(ValueError):
                gen.command_line(system, 1)

    def test_rejects_nonpositive_or_boolean_generation(self):
        for number in (0, -1, True, "1"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                gen.command_line(SYSTEM, number)

    def test_namespace_changes_with_each_boot_payload(self):
        hashes = ["a" * 64, "b" * 64, "c" * 64]
        baseline = gen.esp_namespace(1, *hashes)
        for i in range(3):
            changed = hashes.copy()
            changed[i] = "d" * 64
            self.assertNotEqual(baseline, gen.esp_namespace(1, *changed))

    def test_valid_bundle_bls_and_absolute_target_paths(self):
        directory, meta = self.bundle()
        verified = esp.verify_generation(directory)
        self.assertEqual(verified, meta)
        entry = esp.bls_entry(meta, (directory / "options").read_text())
        self.assertIn("devicetree /" + meta["esp_namespace"] + "/elden.dtb\n", entry)
        self.assertIn("initrd /" + meta["esp_namespace"] + "/initrd.gz\n", entry)

    def test_tampering_detected_before_copy(self):
        directory, _ = self.bundle()
        (directory / "initrd.gz").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            esp.verify_generation(directory)

    def test_different_kernel_with_updated_bundle_hash_is_rejected(self):
        directory, meta = self.bundle()
        with (directory / "linux.efi").open("ab") as stream:
            stream.write(b"changed")
        meta["files"]["linux.efi"] = gen.sha(directory / "linux.efi")
        (directory / "metadata.json").write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, "verified kernel"):
            esp.verify_generation(directory)

    def test_symlink_artifact_is_rejected(self):
        directory, _ = self.bundle()
        original = directory / "initrd.gz"
        original.rename(directory / "other")
        original.symlink_to("other")
        with self.assertRaisesRegex(ValueError, "regular files"):
            esp.verify_generation(directory)

    def test_duplicate_generation_and_absent_default_are_rejected(self):
        directory, _ = self.bundle()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            esp.select_generations([directory, directory], 1)
        with self.assertRaisesRegex(ValueError, "absent"):
            esp.select_generations([directory], 2)

    def test_relative_bootspec_path_is_rejected_even_with_updated_hash(self):
        directory, meta = self.bundle()
        path = directory / "boot.json"
        bootspec = json.loads(path.read_text())
        bootspec["org.nixos.bootspec.v1"]["kernel"] = "linux.efi"
        path.write_text(json.dumps(bootspec))
        meta["files"]["boot.json"] = gen.sha(path)
        (directory / "metadata.json").write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError, "target path"):
            esp.verify_generation(directory)

    def test_forced_builtin_dtb_is_rejected(self):
        source = json.loads((gen.VENDOR / "sources.json").read_text())["kernel"]
        (self.directory / "metadata.json").write_text(json.dumps({
            "schema": 1, "kernel": source,
            "files": dict.fromkeys(("Image", "elden.dtb", "kernel.config", "kernel.release"), "hash"),
        }))
        (self.directory / "kernel.config").write_text("\n".join([
            "CONFIG_EFI=y", "CONFIG_EFI_STUB=y", 'CONFIG_INITRAMFS_SOURCE=""',
            'CONFIG_CMDLINE=""', "CONFIG_BLK_DEV_INITRD=y", "CONFIG_BUILTIN_DTB=y",
        ]))
        with patch.object(gen, "sha", return_value="hash"):
            with self.assertRaisesRegex(ValueError, "Built-in DTB"):
                gen.verify_kernel(self.directory)

    def test_readonly_marker_is_immutable_initrd_input(self):
        with patch.object(gen.subprocess, "check_output", return_value=b"test-cpio"):
            gen.build_initrd(self.directory, SYSTEM, 2, readonly_root=True)
        listing = (self.directory / "initramfs.list").read_text()
        self.assertEqual(listing.count("file /etc/y700-root-readonly "), 1)
        self.assertIn(f"file /etc/y700-root-readonly {self.directory}/root-readonly 0444 0 0", listing)
        self.assertEqual((self.directory / "root-readonly").read_bytes(), b"readonly-overlay\n")

    def test_persistent_initrd_does_not_enable_overlay(self):
        with patch.object(gen.subprocess, "check_output", return_value=b"test-cpio"):
            gen.build_initrd(self.directory, SYSTEM, 2)
        self.assertNotIn("y700-root-readonly", (self.directory / "initramfs.list").read_text())

    def readonly_entries(self):
        return [
            ("init", 0o100755, (gen.VENDOR / "initramfs/init").read_bytes()),
            ("etc", 0o40755, b""),
            ("etc/y700-root-readonly", 0o100444, b"readonly-overlay\n"),
            ("etc/y700-efi-system", 0o100444, (SYSTEM + "\n").encode()),
            ("etc/y700-efi-generation", 0o100444, b"1\n"),
        ]

    def readonly_archive(self, *, omitted=None, changed=None, duplicate=False, appended=False):
        items = self.readonly_entries()
        if omitted:
            items = [entry for entry in items if entry[0] != omitted]
        if changed:
            items = [(name, 0o120777, b"elsewhere") if name == changed else (name, mode, body)
                     for name, mode, body in items]
        if duplicate:
            items.append(items[0])
        return self.write_readonly_archive(items, appended=b"another archive" if appended else b"")

    def write_readonly_archive(self, items, *, links=None, appended=b"",
                               trim_padding=False, raw_fields=None):
        archive = bytearray()
        for number, (name, mode, body) in enumerate([*items, ("TRAILER!!!", 0, b"")], 1):
            encoded = name.encode() + b"\0"
            inode, nlink = (links or {}).get(name, (number, 2 if mode == 0o40755 else 1))
            fields = [inode, mode, 0, 0, nlink, 0, len(body), 0, 0, 0, 0, len(encoded), 0]
            header = bytearray(b"070701" + "".join(f"{n:08x}" for n in fields).encode())
            for (path, index), value in (raw_fields or {}).items():
                if path == name:
                    self.assertEqual(len(value), 8)
                    header[6 + index * 8:14 + index * 8] = value
            archive += header
            archive += encoded
            archive += b"\0" * (-len(archive) % 4)
            archive += body
            archive += b"\0" * (-len(archive) % 4)
        if trim_padding:
            archive = archive[:-1]
        archive += appended
        (self.directory / "initrd.gz").write_bytes(gzip.compress(archive, mtime=0))
        return {"system": SYSTEM, "generation": 1}

    def test_ram_media_checks_actual_readonly_handoff_files(self):
        meta = self.readonly_archive()
        ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")
        for kwargs in (
            {"omitted": "etc/y700-root-readonly"},
            {"changed": "etc/y700-root-readonly"},
            {"changed": "init"},
            {"duplicate": True},
            {"appended": True},
        ):
            with self.subTest(kwargs=kwargs):
                meta = self.readonly_archive(**kwargs)
                with self.assertRaises(ValueError):
                    ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_init_hardlink_alias(self):
        items = self.readonly_entries() + [("init-alias", 0o100755, b"different init\n")]
        meta = self.write_readonly_archive(
            items, links={"init": (1, 2), "init-alias": (1, 2)})
        with self.assertRaisesRegex(ValueError, "hardlink"):
            ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_reused_regular_inode_and_invalid_link_count(self):
        for links in (
            {"etc/y700-root-readonly": (1, 1)},
            {"init": (1, 0)},
            {"etc/y700-efi-system": (4, 2)},
        ):
            with self.subTest(links=links):
                meta = self.write_readonly_archive(self.readonly_entries(), links=links)
                with self.assertRaisesRegex(ValueError, "hardlink"):
                    ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_missing_late_or_non_directory_parent(self):
        missing = [entry for entry in self.readonly_entries() if entry[0] != "etc"]
        cases = [
            missing,
            missing + [("etc", 0o40755, b"")],
            [("etc", 0o120777, b"elsewhere"), *missing],
            [("etc", 0o100644, b""), *missing],
            [("elsewhere", 0o40755, b""), ("etc", 0o120777, b"elsewhere"), *missing],
            [*self.readonly_entries(), ("etc/alias", 0o120777, b".."),
             ("etc/alias/init", 0o100755, b"different init\n")],
        ]
        for items in cases:
            with self.subTest(items=[entry[0] for entry in items]):
                meta = self.write_readonly_archive(items)
                with self.assertRaisesRegex(ValueError, "preceding directory"):
                    ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_accepts_leaf_symlink_and_nested_directories(self):
        items = [*self.readonly_entries(), ("bin", 0o40755, b""),
                 ("bin/sh", 0o120777, b"busybox\0"), ("bin/init", 0o120777, b"/init"),
                 ("lib", 0o40755, b""),
                 ("lib/firmware", 0o40755, b""), ("lib/firmware/test", 0o100444, b"fixture"),
                 ("dev", 0o40755, b""), ("dev/console", 0o20600, b"")]
        meta = self.write_readonly_archive(items)
        ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_directory_or_special_node_with_body(self):
        for mode in (0o40755, 0o20600, 0o60600, 0o10600, 0o140600):
            with self.subTest(mode=oct(mode)):
                items = [(name, mode, b"not empty") if name == "etc" else (name, kind, body)
                         for name, kind, body in self.readonly_entries()]
                meta = self.write_readonly_archive(items)
                with self.assertRaisesRegex(ValueError, "node has a body"):
                    ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_nonhex_header_fields(self):
        for value in (b"+0000001", b" 0000001", b"00000_01"):
            for index in (0, 4, 12):
                with self.subTest(value=value, index=index):
                    meta = self.write_readonly_archive(
                        self.readonly_entries(),
                        raw_fields={("etc/y700-root-readonly", index): value})
                    with self.assertRaisesRegex(ValueError, "Nonhex"):
                        ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_invalid_node_and_symlink_records(self):
        for mode, body in ((0, b""), (0x10000 | 0o40755, b""),
                           (0o120777, b""), (0o120777, b"\0"), (0o120777, b"init\0alias"),
                           (0o120777, b"x" * 4097)):
            with self.subTest(mode=oct(mode), body_size=len(body)):
                meta = self.write_readonly_archive(
                    [*self.readonly_entries(), ("extra", mode, body)])
                with self.assertRaises(ValueError):
                    ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_directory_replacement(self):
        items = [*self.readonly_entries(), ("etc", 0o120777, b"elsewhere")]
        meta = self.write_readonly_archive(items)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_truncated_trailer_alignment(self):
        meta = self.write_readonly_archive(self.readonly_entries(), trim_padding=True)
        with self.assertRaisesRegex(ValueError, "Truncated"):
            ram.verify_readonly_initrd(self.directory, meta, gen.VENDOR / "initramfs/init")

    def test_ram_media_rejects_persistent_generation(self):
        directory, _ = self.bundle()
        with self.assertRaisesRegex(ValueError, "root mode"):
            ram.generation_files(directory, directory / "linux.efi")

    def test_persistent_initrd_requires_absent_readonly_marker(self):
        meta = self.readonly_archive()
        with self.assertRaisesRegex(ValueError, "read-only marker"):
            ram.verify_readonly_initrd(
                self.directory, meta, gen.VENDOR / "initramfs/init", persistent=True)
        meta = self.readonly_archive(omitted="etc/y700-root-readonly")
        ram.verify_readonly_initrd(
            self.directory, meta, gen.VENDOR / "initramfs/init", persistent=True)

if __name__ == "__main__":
    unittest.main()
