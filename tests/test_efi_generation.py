import importlib.util
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


if __name__ == "__main__":
    unittest.main()
