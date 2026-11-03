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


if __name__ == "__main__":
    unittest.main()
