import copy
import importlib.util
import os
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import zlib

from test_storage_layout import snapshot
from test_recovery_reset import backup as misc_backup, reset

spec = importlib.util.spec_from_file_location(
    "storage_write", Path(__file__).resolve().parents[1] / "tools/prepare-storage-write.py")
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)
GUIDS = [str(uuid.UUID(int=301)), str(uuid.UUID(int=302))]


class StorageWriteTests(unittest.TestCase):
    def prepare(self):
        return writer.prepare(snapshot(), 256, GUIDS)

    def disk(self, directory, transaction):
        path = Path(directory) / "disk.raw"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.ftruncate(fd, transaction["before"]["disk_bytes"])
        for record in transaction["before"]["regions"].values():
            os.pwrite(fd, writer.bytes_of(record), record["offset"])
        return fd

    def valid_copy(self, fd, transaction, side):
        record = transaction["before"]["regions"][side + "_header"]
        raw = bytearray(os.pread(fd, 4096, record["offset"]))
        length = struct.unpack_from("<I", raw, 12)[0]
        recorded = struct.unpack_from("<I", raw, 16)[0]
        struct.pack_into("<I", raw, 16, 0)
        if zlib.crc32(raw[:length]) != recorded:
            return False
        lba, count, stride, crc = struct.unpack_from("<QIII", raw, 72)
        return zlib.crc32(os.pread(fd, count * stride, lba * 4096)) == crc

    def test_256gib_preserves_existing_guid_attributes_and_padding(self):
        original = snapshot()
        transaction = writer.prepare(original, 256, GUIDS)
        writer.validate_transaction(transaction)
        before = writer.bytes_of(original["regions"]["primary_entries"])
        after = writer.bytes_of(transaction["after"]["regions"]["primary_entries"])
        self.assertEqual(before[:128], after[:128])
        self.assertEqual(before[128:168], after[128:168])
        self.assertEqual(before[176:256], after[176:256])
        self.assertEqual(before[512:], after[512:])
        self.assertEqual(transaction["proposal"]["userdata"]["proposed_bytes"], 208034693120)
        self.assertEqual(transaction["proposal"]["new_partitions"][0]["start"], 56762112)
        self.assertEqual(transaction["proposal"]["new_partitions"][1]["start"], 57024256)
        self.assertEqual(transaction["after"]["regions"]["pmbr"], original["regions"]["pmbr"])

    def test_complete_transaction_and_sentinels(self):
        transaction = self.prepare()
        with tempfile.TemporaryDirectory() as directory:
            fd = self.disk(directory, transaction)
            try:
                offsets = [16384, 5972392 * 4096, 56762112 * 4096,
                           57024256 * 4096, 123870975 * 4096]
                for offset in offsets:
                    os.pwrite(fd, b"ANDROID_AND_DATA_SENTINEL", offset)
                writer.apply_to_fd(fd, transaction)
                writer.assert_snapshot(fd, transaction["after"])
                self.assertTrue(self.valid_copy(fd, transaction, "primary"))
                self.assertTrue(self.valid_copy(fd, transaction, "backup"))
                for offset in offsets:
                    self.assertEqual(os.pread(fd, 25, offset), b"ANDROID_AND_DATA_SENTINEL")
            finally:
                os.close(fd)

    def test_every_interruption_boundary_retains_a_valid_copy(self):
        transaction = self.prepare()
        for stop in writer.ORDER:
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as directory:
                fd = self.disk(directory, transaction)
                try:
                    def crash(name):
                        if name == stop:
                            raise InterruptedError("simulated")
                    with self.assertRaises(InterruptedError):
                        writer.apply_to_fd(fd, transaction, crash)
                    self.assertTrue(self.valid_copy(fd, transaction, "primary") or
                                    self.valid_copy(fd, transaction, "backup"))
                finally:
                    os.close(fd)

    def test_stale_snapshot_refuses_before_any_write(self):
        transaction = self.prepare()
        with tempfile.TemporaryDirectory() as directory:
            fd = self.disk(directory, transaction)
            try:
                os.pwrite(fd, b"x", 450)
                before = {n: os.pread(fd, len(writer.bytes_of(r)), r["offset"])
                          for n, r in transaction["before"]["regions"].items()}
                with self.assertRaisesRegex(ValueError, "differs from snapshot"):
                    writer.apply_to_fd(fd, transaction)
                for name, record in transaction["before"]["regions"].items():
                    self.assertEqual(os.pread(fd, len(before[name]), record["offset"]),
                                     before[name])
            finally:
                os.close(fd)

    def test_reset_is_armed_at_every_gpt_interruption_boundary(self):
        transaction = self.prepare()
        misc_offset = 2 * 1024 * 1024
        misc = misc_backup()
        armed = reset.prepare(misc, keep_memtag=True)
        for stop in ("bcb",) + writer.ORDER:
            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as directory:
                fd = self.disk(directory, transaction)
                try:
                    os.pwrite(fd, misc, misc_offset)
                    os.pwrite(fd, armed[:4096], misc_offset)
                    os.fsync(fd)
                    if stop != "bcb":
                        def crash(name):
                            if name == stop:
                                raise InterruptedError("simulated")
                        with self.assertRaises(InterruptedError):
                            writer.apply_to_fd(fd, transaction, crash)
                    self.assertEqual(os.pread(fd, len(misc), misc_offset), armed)
                    self.assertTrue(self.valid_copy(fd, transaction, "primary") or
                                    self.valid_copy(fd, transaction, "backup"))
                finally:
                    os.close(fd)

    def test_modified_payload_cannot_add_writes_or_change_other_entries(self):
        transaction = self.prepare()
        for field in ("offset", "base64", "write_order"):
            changed = copy.deepcopy(transaction)
            if field == "write_order":
                changed[field] = list(reversed(writer.ORDER))
            elif field == "offset":
                changed["after"]["regions"]["primary_entries"][field] += 4096
            else:
                raw = bytearray(writer.bytes_of(changed["after"]["regions"]["primary_entries"]))
                raw[32] ^= 1
                changed["after"]["regions"]["primary_entries"] = writer.region(raw, 8192)
            with self.assertRaisesRegex(ValueError, "allowed changes"):
                writer.validate_transaction(changed)

    def test_duplicate_zero_and_existing_guid_refused(self):
        for guids in ([GUIDS[0]] * 2, [str(uuid.UUID(int=0)), GUIDS[1]],
                      [str(uuid.UUID(int=1)), GUIDS[1]]):
            with self.assertRaisesRegex(ValueError, "unique and nonzero"):
                writer.prepare(snapshot(), 256, guids)


if __name__ == "__main__":
    unittest.main()
