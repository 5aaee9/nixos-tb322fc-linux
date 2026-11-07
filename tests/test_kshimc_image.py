"""Use the real native packer to test the independent Android-base verifier."""

import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import kshimc_image as image


class ImageVerificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        packer = os.environ.get("KSHIM_PACKER")
        if not packer or not Path(packer).is_file():
            raise RuntimeError("Set KSHIM_PACKER to the source-built MultiBootKernelPatcher")
        with tempfile.TemporaryDirectory(prefix="kshimc-verifier-") as temporary:
            root = Path(temporary)
            kernel = bytearray(65536)
            struct.pack_into("<I", kernel, 0, 0x14000010)
            struct.pack_into("<Q", kernel, 16, 131072)
            kernel[56:60] = b"ARM\x64"
            cls.runtime = bytes(image.RUNTIME_BYTES)
            (root / "kernel").write_bytes(kernel)
            (root / "runtime").write_bytes(cls.runtime)
            (root / "pack.ini").write_text(
                f"[Pack]\nShim = {root / 'runtime'}\nOutput = {root / 'packed'}\n"
                "Default = Image-00\nTimeout = 10000\n\n[Image-00]\nName = Android\n"
                f"Path = {root / 'kernel'}\nType = Linux\nBaseImage = true\nAlign = 21\n"
                "\n[Manifest]\nType = Manifest\n"
            )
            subprocess.run([packer, str(root / "pack.ini")], check=True, capture_output=True)
            cls.packed = (root / "packed").read_bytes()
            stock = bytearray(image.PARTITION_BYTES)
            stock[:8] = b"ANDROID!"
            struct.pack_into("<I", stock, 8, len(kernel))
            struct.pack_into("<I", stock, 20, 1584)
            struct.pack_into("<I", stock, 40, 4)
            stock[image.PAGE:image.PAGE + len(kernel)] = kernel
            stock[-64:-60] = b"AVBf"
            cls.stock = bytes(stock)
            cls.stock_hash = image.sha256(cls.stock)
            cls.boot = image.wrap_boot(cls.stock, cls.packed)
            linux = bytearray(kernel)
            # A small file with a deliberately large BSS exercises the separate
            # RAM ceiling and reservation without fabricating a large kernel.
            struct.pack_into("<Q", linux, 16, 100 * 1024 * 1024)
            struct.pack_into("<Q", linux, 24, 0xA)
            cls.linux = bytes(linux)
            (root / "linux").write_bytes(linux)
            config = (root / "pack.ini").read_text().replace(
                "\n[Manifest]",
                f"\n[Image-01]\nName = {image.LINUX_NAME.decode()}\n"
                f"Path = {root / 'linux'}\nType = Linux\nAlign = 21\n\n[Manifest]",
            )
            (root / "pack.ini").write_text(config)
            subprocess.run([packer, str(root / "pack.ini")], check=True, capture_output=True)
            cls.linux_packed = (root / "packed").read_bytes()
            cls.linux_boot = image.wrap_ram_linux_boot(cls.stock, cls.linux_packed)
            cls.linux_layout = image.verify_ram_linux_boot(
                cls.linux_boot, cls.stock, cls.runtime, cls.linux, cls.stock_hash)
            provider = bytearray(kernel)
            struct.pack_into("<Q", provider, 16, 0x20000)
            struct.pack_into("<Q", provider, 24, 0xA)
            marker = b"Y700_RAM_UEFI_PROVIDER=v1"
            provider[128:128 + len(marker)] = marker
            cls.provider = bytes(provider)
            (root / "provider").write_bytes(provider)
            # Minimal valid FDT: header, terminator reservation, root and END.
            structure = struct.pack(">I4xIII", 1, 2, 9, 0)[:16]
            cls.dtb = struct.pack(">10I", 0xD00DFEED, 72, 56, 72, 40, 17, 16, 0, 0, 16)
            cls.dtb += bytes(16) + structure
            (root / "board.dtb").write_bytes(cls.dtb)
            config = config.replace(image.LINUX_NAME.decode(), image.UEFI_NAME.decode())
            config = config.replace(str(root / "linux"), str(root / "provider"))
            config = config.replace("\n[Manifest]",
                f"DeviceTreeBlob = Image-02\n\n[Image-02]\nName = UEFI board DT\n"
                f"Path = {root / 'board.dtb'}\nType = DTB\nAlign = 3\n\n[Manifest]")
            (root / "pack.ini").write_text(config)
            subprocess.run([packer, str(root / "pack.ini")], check=True, capture_output=True)
            cls.uefi_packed = (root / "packed").read_bytes()
            cls.uefi_boot = image.wrap_ram_linux_boot(cls.stock, cls.uefi_packed)
            cls.uefi_layout = image.verify_ram_uefi_boot(
                cls.uefi_boot, cls.stock, cls.runtime, cls.provider, cls.dtb, cls.stock_hash)

    def verify(self, boot=None, runtime=None, stock=None, stock_hash=None):
        return image.verify_boot(
            self.boot if boot is None else boot,
            self.stock if stock is None else stock,
            self.runtime if runtime is None else runtime,
            self.stock_hash if stock_hash is None else stock_hash,
        )

    def corrupt(self, offset, value):
        modified = bytearray(self.boot)
        modified[offset] ^= value
        return bytes(modified)

    def test_native_packer_round_trip(self):
        self.assertEqual(self.verify()["stock_restoration"], "byte-identical")

    def test_wrong_stock_hash(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.verify(stock_hash="0" * 64)

    def test_changed_android_kernel(self):
        with self.assertRaisesRegex(ValueError, "kernel was not preserved"):
            self.verify(boot=self.corrupt(image.PAGE + 512, 1))

    def test_changed_android_continuation(self):
        modified = bytearray(self.boot)
        struct.pack_into("<I", modified, image.PAGE + 4, 0xD4200000)
        with self.assertRaisesRegex(ValueError, "continuation instruction"):
            self.verify(boot=bytes(modified))

    def runtime_entry(self):
        manifest = image.PAGE + image.u64(self.packed, 32)
        first = manifest + 60
        return first + ((56 + image.u32(self.boot, first + 52) + 3) & ~3)

    def test_invalid_runtime_alignment(self):
        modified = bytearray(self.boot)
        struct.pack_into("<I", modified, self.runtime_entry() + 40, 0)
        with self.assertRaisesRegex(ValueError, "runtime alignment"):
            self.verify(boot=bytes(modified))

    def test_invalid_runtime_name(self):
        modified = bytearray(self.boot)
        modified[self.runtime_entry() + 56] = 0
        with self.assertRaisesRegex(ValueError, "name terminator"):
            self.verify(boot=bytes(modified))

    def test_changed_runtime(self):
        runtime = b"x" + self.runtime[1:]
        with self.assertRaisesRegex(ValueError, "Runtime byte"):
            self.verify(runtime=runtime)

    def test_changed_entry_branch(self):
        with self.assertRaisesRegex(ValueError, "branch misses"):
            self.verify(boot=self.corrupt(image.PAGE, 1))

    def test_changed_default(self):
        manifest_offset = image.u64(self.packed, 32)
        with self.assertRaisesRegex(ValueError, "diagnostic manifest"):
            self.verify(boot=self.corrupt(image.PAGE + manifest_offset + 12, 1))

    def test_changed_boot_metadata(self):
        with self.assertRaisesRegex(ValueError, "boot-header modification"):
            self.verify(boot=self.corrupt(16, 1))

    def test_truncated_boot(self):
        with self.assertRaisesRegex(ValueError, "trailing extent"):
            self.verify(boot=self.boot[:-1])

    def test_nonzero_padding(self):
        with self.assertRaisesRegex(ValueError, "padding"):
            self.verify(boot=self.corrupt(len(self.boot) - 1, 1))

    def verify_linux(self, boot=None, linux=None):
        return image.verify_ram_linux_boot(
            self.linux_boot if boot is None else boot, self.stock, self.runtime,
            self.linux if linux is None else linux, self.stock_hash)

    def linux_entry(self):
        manifest = image.PAGE + image.u64(self.linux_packed, 32)
        first = manifest + 60
        return first + ((56 + image.u32(self.linux_boot, first + 52) + 3) & ~3)

    def test_linux_native_round_trip_and_reserved_bss(self):
        layout = self.verify_linux()
        self.assertEqual(layout["entries"], 3)
        self.assertEqual(layout["linux_memory_bytes"], 100 * 1024 * 1024)
        self.assertGreater(len(self.linux_boot), image.PARTITION_BYTES)
        self.assertEqual(layout["stock_restoration"], "byte-identical")

    def test_linux_oversize_does_not_relax_installed_limit(self):
        with self.assertRaisesRegex(ValueError, "capacity"):
            image.wrap_boot(self.stock, self.linux_packed)
        with self.assertRaisesRegex(ValueError, "size out of bounds"):
            self.verify(boot=self.linux_boot)
        with self.assertRaisesRegex(ValueError, "capacity"):
            image.wrap_ram_linux_boot(self.stock, bytes(image.RAM_IMAGE_LIMIT))

    def test_linux_does_not_replace_default(self):
        modified = bytearray(self.linux_boot)
        manifest = image.PAGE + image.u64(self.linux_packed, 32)
        struct.pack_into("<I", modified, manifest + 12, 1)
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.verify_linux(boot=modified)

    def test_linux_copy_or_dtb_flags_rejected(self):
        for flags in (6, 12):
            with self.subTest(flags=flags):
                modified = bytearray(self.linux_boot)
                struct.pack_into("<I", modified, self.linux_entry() + 20, flags)
                with self.assertRaisesRegex(ValueError, "Linux entry"):
                    self.verify_linux(boot=modified)

    def test_linux_header_bss_crossing_manifest(self):
        linux = bytearray(self.linux)
        struct.pack_into("<Q", linux, 16, 110 * 1024 * 1024)
        modified = bytearray(self.linux_boot)
        offset = image.PAGE + self.linux_layout["linux_offset"]
        modified[offset:offset + len(linux)] = linux
        with self.assertRaisesRegex(ValueError, "BSS overlaps"):
            self.verify_linux(boot=modified, linux=linux)

    def test_linux_misaligned_offset(self):
        modified = bytearray(self.linux_boot)
        struct.pack_into("<Q", modified, self.linux_entry(),
                         self.linux_layout["linux_offset"] - 4)
        with self.assertRaisesRegex(ValueError, "Misaligned Linux"):
            self.verify_linux(boot=modified)

    def test_linux_overlaps_runtime(self):
        modified = bytearray(self.linux_boot)
        struct.pack_into("<Q", modified, self.linux_entry(), image.LINUX_ALIGNMENT)
        with self.assertRaisesRegex(ValueError, "overlaps runtime"):
            self.verify_linux(boot=modified)

    def test_linux_corruption(self):
        modified = bytearray(self.linux_boot)
        modified[image.PAGE + self.linux_layout["linux_offset"] + 512] ^= 1
        with self.assertRaisesRegex(ValueError, "Linux byte mismatch"):
            self.verify_linux(boot=modified)

    def test_linux_dirty_bss(self):
        modified = bytearray(self.linux_boot)
        modified[image.PAGE + self.linux_layout["linux_offset"] + len(self.linux)] = 1
        with self.assertRaisesRegex(ValueError, "padding/BSS"):
            self.verify_linux(boot=modified)

    def verify_uefi(self, boot=None, provider=None, dtb=None):
        return image.verify_ram_uefi_boot(
            self.uefi_boot if boot is None else boot, self.stock, self.runtime,
            self.provider if provider is None else provider,
            self.dtb if dtb is None else dtb, self.stock_hash)

    def test_uefi_real_packer_preserves_android_and_binds_dtb(self):
        self.assertEqual(self.verify_uefi()["entries"], 4)
        self.assertEqual(self.verify_uefi()["stock_restoration"], "byte-identical")
        self.assertNotIn("linux_sha256", self.verify_uefi())

    def test_uefi_refuses_missing_provider_marker(self):
        with self.assertRaisesRegex(ValueError, "provider marker"):
            self.verify_uefi(provider=bytes(len(self.provider)))

    def test_uefi_refuses_changed_dtb(self):
        changed = bytearray(self.uefi_boot)
        changed[image.PAGE + self.uefi_layout["uefi_dtb_offset"] + 24] ^= 1
        with self.assertRaisesRegex(ValueError, "DT byte mismatch"):
            self.verify_uefi(boot=changed)

    def test_uefi_cannot_pass_linux_contract(self):
        with self.assertRaisesRegex(ValueError, "manifest"):
            image.verify_ram_linux_boot(self.uefi_boot, self.stock, self.runtime,
                                        self.provider, self.stock_hash)

    def test_installed_uefi_requires_linux_default_and_preserves_android(self):
        with self.assertRaisesRegex(ValueError, "manifest"):
            image.verify_installed_uefi_boot(
                self.uefi_boot, self.stock, self.runtime,
                self.provider, self.dtb, self.stock_hash)
        installed = bytearray(self.uefi_boot)
        struct.pack_into("<I", installed, image.PAGE + self.uefi_layout["manifest_offset"] + 12, 1)
        layout = image.verify_installed_uefi_boot(
            installed, self.stock, self.runtime, self.provider, self.dtb, self.stock_hash)
        self.assertEqual(layout["stock_restoration"], "byte-identical")
        self.assertEqual(layout["default_index"], 1)
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.verify_uefi(boot=installed)


if __name__ == "__main__":
    unittest.main()
