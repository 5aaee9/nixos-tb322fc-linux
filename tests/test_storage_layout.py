import base64
import copy
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest
import uuid
import zlib

spec = importlib.util.spec_from_file_location(
    "layout", Path(__file__).resolve().parents[1] / "tools/storage-layout.py")
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


def region(data, offset):
    digest = hashlib.sha256(data).hexdigest()
    return dict(offset=offset, base64=base64.b64encode(data).decode(),
                sha256=digest, readback_sha256=digest)


def snapshot():
    sector = 4096
    sectors = 123871232
    entries = bytearray(4096)
    for i, (label, first, last) in enumerate([
        ("super", 6, 5972391), ("userdata", 5972392, sectors - 6),
    ]):
        at = i * 128
        entries[at:at + 16] = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4").bytes_le
        entries[at + 16:at + 32] = uuid.UUID(int=i + 1).bytes_le
        struct.pack_into("<QQQ", entries, at + 32, first, last, 0)
        entries[at + 56:at + 56 + len(label) * 2] = label.encode("utf-16-le")

    def header(current, alternate, table_lba):
        data = bytearray(sector)
        layout.HEADER.pack_into(data, 0, b"EFI PART", 0x10000, 92, 0, 0,
                                current, alternate, 6, sectors - 6,
                                uuid.UUID(int=100).bytes_le, table_lba, 32, 128,
                                zlib.crc32(entries))
        struct.pack_into("<I", data, 16, zlib.crc32(data[:92]))
        return data

    mbr = bytearray(sector)
    mbr[450] = 0xEE
    mbr[510:512] = b"\x55\xaa"
    return dict(schema=1, sector_size=sector, disk_bytes=sectors * sector, regions={
        "pmbr": region(mbr, 0),
        "primary_header": region(header(1, sectors - 1, 2), sector),
        "primary_entries": region(entries, sector * 2),
        "backup_entries": region(entries, (sectors - 2) * sector),
        "backup_header": region(header(sectors - 1, 1, sectors - 2), (sectors - 1) * sector),
    })


def replace_entries(capture, entries):
    for name in ("primary_entries", "backup_entries"):
        capture["regions"][name] = region(entries, capture["regions"][name]["offset"])
    for name in ("primary_header", "backup_header"):
        data = bytearray(base64.b64decode(capture["regions"][name]["base64"]))
        struct.pack_into("<I", data, 88, zlib.crc32(entries))
        struct.pack_into("<I", data, 16, 0)
        struct.pack_into("<I", data, 16, zlib.crc32(data[:92]))
        capture["regions"][name] = region(data, capture["regions"][name]["offset"])


class StorageLayoutTests(unittest.TestCase):
    def test_capacity_alignment_and_accounting(self):
        capture = snapshot()
        original = copy.deepcopy(capture)
        for budget in (64, 128):
            result = layout.plan(capture, budget)
            u = result["userdata"]
            esp, root = result["new_partitions"]
            self.assertEqual(u["start_lba_unchanged"], 5972392)
            self.assertEqual(esp["start"] % 256, 0)
            self.assertEqual(root["start"] % 256, 0)
            self.assertEqual(esp["end"] + 1, root["start"])
            self.assertEqual(u["proposed_end_lba"] + 1, esp["start"])
            self.assertEqual(esp["bytes"], 1 << 30)
            self.assertEqual(root["bytes"], (budget - 1) << 30)
            self.assertEqual(u["proposed_bytes"] + budget * (1 << 30) +
                             result["tail_alignment_bytes"], u["old_bytes"])
            self.assertFalse(u["filesystem_resize_validated"])
            self.assertEqual(result["tail_alignment_bytes"], 1028096)
        self.assertEqual(capture, original)

    def test_corrupt_header_crc(self):
        c = snapshot()
        data = bytearray(base64.b64decode(c["regions"]["primary_header"]["base64"]))
        data[56] ^= 1
        c["regions"]["primary_header"] = region(data, 4096)
        with self.assertRaisesRegex(ValueError, "header CRC"):
            layout.plan(c, 64)

    def test_backup_array_differs(self):
        c = snapshot()
        data = bytearray(base64.b64decode(c["regions"]["backup_entries"]["base64"]))
        data[60] ^= 1
        c["regions"]["backup_entries"] = region(data, c["regions"]["backup_entries"]["offset"])
        with self.assertRaisesRegex(ValueError, "entry arrays differ"):
            layout.plan(c, 64)

    def test_transfer_hash_and_repeat_read(self):
        for field in ("sha256", "readback_sha256"):
            c = snapshot()
            c["regions"]["primary_entries"][field] = "0" * 64
            with self.assertRaises(ValueError):
                layout.plan(c, 64)

    def test_duplicate_userdata_and_overlap(self):
        for mutation in ("label", "overlap"):
            c = snapshot()
            data = bytearray(base64.b64decode(c["regions"]["primary_entries"]["base64"]))
            if mutation == "label":
                data[56:128] = "userdata".encode("utf-16-le").ljust(72, b"\0")
            else:
                struct.pack_into("<Q", data, 40, 5972392)
            replace_entries(c, data)
            with self.assertRaisesRegex(ValueError, "exactly one|overlapping"):
                layout.plan(c, 64)

    def test_type_zero_tail_is_not_free_space(self):
        c = snapshot()
        data = bytearray(base64.b64decode(c["regions"]["primary_entries"]["base64"]))
        data[2 * 128 + 56] = ord("x")
        replace_entries(c, data)
        with self.assertRaisesRegex(ValueError, "type-zero"):
            layout.plan(c, 64)
        with self.assertRaisesRegex(ValueError, "type-zero"):
            layout.decode_capture(c)
        original = copy.deepcopy(c)
        _, partitions = layout.decode_capture(c, allow_vendor_reservations=True)
        self.assertEqual([p["label"] for p in partitions], ["super", "userdata"])
        self.assertEqual(c, original)
        with self.assertRaisesRegex(ValueError, "type-zero"):
            layout.plan(c, 256)

    def test_read_only_vendor_inventory_still_checks_crc_and_copies(self):
        c = snapshot()
        data = bytearray(base64.b64decode(c["regions"]["primary_entries"]["base64"]))
        data[2 * 128 + 56] = ord("x")
        replace_entries(c, data)
        data[2 * 128 + 57] = ord("y")
        c["regions"]["backup_entries"] = region(data, c["regions"]["backup_entries"]["offset"])
        with self.assertRaisesRegex(ValueError, "entry arrays differ"):
            layout.decode_capture(c, allow_vendor_reservations=True)

    def test_reject_incorrect_geometry_and_capacity(self):
        c = snapshot()
        c["sector_size"] = 512
        with self.assertRaises(ValueError):
            layout.plan(c, 64)
        for budget in (-1, 0, 1, 512, 1.5):
            with self.assertRaises(ValueError):
                layout.plan(snapshot(), budget)

    def test_reject_hybrid_mbr_and_wrong_capture_offset(self):
        c = snapshot()
        data = bytearray(base64.b64decode(c["regions"]["pmbr"]["base64"]))
        data[466] = 0x83
        c["regions"]["pmbr"] = region(data, 0)
        with self.assertRaisesRegex(ValueError, "hybrid"):
            layout.plan(c, 64)
        c = snapshot()
        c["regions"]["backup_entries"]["offset"] -= 4096
        with self.assertRaisesRegex(ValueError, "capture offset"):
            layout.plan(c, 64)


if __name__ == "__main__":
    unittest.main()
