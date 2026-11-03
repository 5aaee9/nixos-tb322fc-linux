import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location(
    "recovery_reset", Path(__file__).resolve().parents[1] / "tools/prepare-recovery-reset.py")
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


def backup():
    data = bytearray(1024 * 1024)
    data[:32] = b"bootonce-bootloader".ljust(32, b"\0")
    data[2048:4096] = b"V" * 2048
    struct.pack_into("<BIBB", data, 32768, 2, 0x56740AB0, 0, 0)
    return bytes(data)


class RecoveryResetTests(unittest.TestCase):
    def test_preserves_slot_control_and_other_misc_fields(self):
        before = backup()
        after = reset.prepare(before, keep_memtag=True)
        changed = {i for i, (a, b) in enumerate(zip(before, after)) if a != b}
        self.assertTrue(changed <= set(range(32)) | set(range(64, 832)))
        self.assertEqual(after[2048:], before[2048:])
        self.assertEqual(after[64:832].split(b"\0")[0],
                         b"recovery\n--wipe_data\n--reason=y700_linux_install\n--keep_memtag_mode\n")

    def test_refuses_pending_operations(self):
        for offset, value in ((0, b"update"), (64, b"recovery\n"), (832, b"1/3"),
                              (32768, b"\x01"), (32773, b"\x03")):
            with self.subTest(offset=offset):
                data = bytearray(backup())
                data[offset:offset + len(value)] = value
                with self.assertRaises(ValueError):
                    reset.prepare(data)

    def test_cannot_rearm_a_wipe_request_implicitly(self):
        with self.assertRaises(ValueError):
            reset.prepare(reset.prepare(backup()))


if __name__ == "__main__":
    unittest.main()
