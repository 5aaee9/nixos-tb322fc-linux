#!/usr/bin/env python3
"""Validate a private GPT snapshot and propose a layout. Never write a disk."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import uuid
import zlib

GIB = 1 << 30
MIB = 1 << 20
HEADER = struct.Struct("<8sIIIIQQQQ16sQIII")
ZERO_GUID = b"\0" * 16


def require(condition, message):
    if not condition:
        raise ValueError(message)


def header(raw, sector_size, sectors, expected_lba):
    require(len(raw) == sector_size, "header sector length")
    fields = HEADER.unpack_from(raw)
    (signature, revision, size, crc, reserved, current, alternate, first,
     last, disk_guid, table_lba, count, entry_size, table_crc) = fields
    require(signature == b"EFI PART" and revision == 0x10000, "GPT signature/revision")
    require(HEADER.size <= size <= sector_size and reserved == 0, "GPT header size/reserved")
    checked = bytearray(raw[:size])
    checked[16:20] = b"\0" * 4
    require(zlib.crc32(checked) == crc, "GPT header CRC")
    require(current == expected_lba, "GPT header location")
    require(alternate == (sectors - 1 if current == 1 else 1), "GPT alternate location")
    require(2 <= first <= last < sectors - 1, "GPT usable range")
    require(disk_guid != ZERO_GUID, "GPT disk GUID is zero")
    require(1 <= count <= 4096, "unsupported GPT entry count")
    require(entry_size >= 128 and entry_size <= 4096 and entry_size % 128 == 0,
            "unsupported GPT entry size")
    table_sectors = (count * entry_size + sector_size - 1) // sector_size
    require(table_lba >= 2 and table_lba + table_sectors <= sectors - 1,
            "GPT table outside disk")
    if current == 1:
        require(table_lba + table_sectors <= first, "primary table overlaps usable space")
    else:
        require(table_lba > last, "backup table overlaps usable space")
    return dict(current=current, alternate=alternate, first=first, last=last,
                guid=disk_guid.hex(), table_lba=table_lba, count=count,
                entry_size=entry_size, table_crc=table_crc)


def decode_capture(capture, *, allow_vendor_reservations=False):
    """Decode checked GPT bytes; vendor reservations are read-only inventory only."""
    require(capture.get("schema") == 1, "snapshot schema")
    sector = capture["sector_size"]
    total = capture["disk_bytes"]
    require(sector in (512, 4096) and total % sector == 0, "disk geometry")
    require(total // sector > 4, "disk too small")
    regions = {}
    for name in ("pmbr", "primary_header", "primary_entries", "backup_entries", "backup_header"):
        item = capture["regions"][name]
        value = base64.b64decode(item["base64"], validate=True)
        require(hashlib.sha256(value).hexdigest() == item["sha256"], f"{name} transfer hash")
        require(item["readback_sha256"] == item["sha256"], f"{name} changed during capture")
        regions[name] = value
    require(len(regions["pmbr"]) == sector and regions["pmbr"][510:512] == b"\x55\xaa",
            "protective MBR signature")
    # Reject a hybrid MBR: changing only GPT would leave a conflicting table.
    mbr_types = [regions["pmbr"][446 + n * 16 + 4] for n in range(4)]
    require(mbr_types.count(0xEE) == 1 and all(x in (0, 0xEE) for x in mbr_types),
            "protective MBR has hybrid/invalid entries")
    primary = header(regions["primary_header"], sector, total // sector, 1)
    backup = header(regions["backup_header"], sector, total // sector, total // sector - 1)
    for field in ("first", "last", "guid", "count", "entry_size", "table_crc"):
        require(primary[field] == backup[field], f"GPT copies differ: {field}")
    expected_offsets = {
        "pmbr": 0, "primary_header": sector,
        "primary_entries": primary["table_lba"] * sector,
        "backup_entries": backup["table_lba"] * sector,
        "backup_header": total - sector,
    }
    for name, offset in expected_offsets.items():
        require(capture["regions"][name]["offset"] == offset, f"{name} capture offset")
    size = primary["count"] * primary["entry_size"]
    table = regions["primary_entries"]
    require(len(table) == size and len(regions["backup_entries"]) == size, "GPT table size")
    require(table == regions["backup_entries"], "GPT entry arrays differ")
    require(zlib.crc32(table) == primary["table_crc"], "GPT entry array CRC")
    partitions = []
    used_guids = set()
    for i in range(primary["count"]):
        entry = table[i * primary["entry_size"]:(i + 1) * primary["entry_size"]]
        if entry[:16] == ZERO_GUID:
            # Other UFS LUNs contain OEM reservations. Inventory may skip them,
            # but planning must never treat their bytes as allocatable slots.
            require(allow_vendor_reservations or not any(entry),
                    "nonempty type-zero GPT entry requires manual assessment")
            continue
        first, last, attrs = struct.unpack_from("<QQQ", entry, 32)
        label = entry[56:128].decode("utf-16-le").split("\0", 1)[0]
        guid = str(uuid.UUID(bytes_le=entry[16:32]))
        require(entry[16:32] != ZERO_GUID and guid not in used_guids, "duplicate/zero partition GUID")
        used_guids.add(guid)
        require(primary["first"] <= first <= last <= primary["last"], "partition outside usable range")
        partitions.append(dict(number=i + 1, label=label, start=first, end=last,
                               sectors=last - first + 1, attrs=attrs, guid=guid,
                               type=str(uuid.UUID(bytes_le=entry[:16])),
                               entry_sha256=hashlib.sha256(entry).hexdigest()))
    ordered = sorted(partitions, key=lambda p: p["start"])
    for a, b in zip(ordered, ordered[1:]):
        require(a["end"] < b["start"], "overlapping GPT partitions")
    return primary, ordered


def plan(capture, linux_gib):
    primary, partitions = decode_capture(capture)
    sector = capture["sector_size"]
    require(sector == 4096, "TB322FC plan requires verified 4096-byte logical sectors")
    require(isinstance(linux_gib, int) and 16 <= linux_gib <= 256, "Linux budget must be 16..256 GiB")
    matches = [p for p in partitions if p["label"] == "userdata"]
    require(len(matches) == 1, "expected exactly one userdata partition")
    require(not any(p["label"] in ("rootfs", "linux-esp") for p in partitions),
            "Linux label already exists; do not propose a second install")
    userdata = matches[0]
    require(userdata is partitions[-1] and userdata["end"] == primary["last"],
            "userdata must be final and extend to last usable LBA")
    require(userdata["attrs"] & (1 << 60) == 0, "userdata is marked read-only")
    free_slots = sorted(set(range(1, primary["count"] + 1)) -
                        {p["number"] for p in partitions})
    require(len(free_slots) >= 2, "two unused GPT slots required")
    alignment = MIB // sector
    end_exclusive = ((userdata["end"] + 1) // alignment) * alignment
    start = end_exclusive - linux_gib * GIB // sector
    require(start > userdata["start"], "Linux budget consumes userdata")
    require((start - userdata["start"]) * sector >= 32 * GIB, "leave at least 32 GiB for Android")
    esp_end = start + GIB // sector - 1
    new_userdata_bytes = (start - userdata["start"]) * sector
    return {
        "status": "proposal-only; no resize or disk-write commands",
        "linux_budget_gib": linux_gib, "sector_size": sector,
        "disk_bytes": capture["disk_bytes"],
        "snapshot_sha256": hashlib.sha256(
            json.dumps(capture, sort_keys=True).encode()).hexdigest(),
        "userdata": {
            "number": userdata["number"], "start_lba_unchanged": userdata["start"],
            "old_end_lba": userdata["end"], "proposed_end_lba": start - 1,
            "old_bytes": userdata["sectors"] * sector,
            "proposed_bytes": new_userdata_bytes, "proposed_gib": new_userdata_bytes / GIB,
            "filesystem_resize_validated": False,
        },
        "new_partitions": [
            {"number": free_slots[0], "label": "linux-esp", "start": start, "end": esp_end,
             "bytes": GIB, "type": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
            {"number": free_slots[1], "label": "rootfs", "start": esp_end + 1,
             "end": end_exclusive - 1, "bytes": (linux_gib - 1) * GIB,
             "type": "0fc63daf-8483-4772-8e79-3d69d8477de4"},
        ],
        "tail_alignment_bytes": (userdata["end"] + 1 - end_exclusive) * sector,
        "unchanged_entries": [{"number": p["number"], "label": p["label"],
                               "entry_sha256": p["entry_sha256"]}
                              for p in partitions if p is not userdata],
        "gates": [
            "owner selects capacity and Android data policy",
            "validated encrypted-F2FS shrink or approved recreation and recovery",
            "verified matching backups and fresh unmounted-device identity",
            "independent review of exact installer and write set",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--linux-gib", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = plan(json.loads(args.snapshot.read_text()), args.linux_gib)
        with args.output.open("x") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    except (ValueError, KeyError, TypeError, OSError, struct.error) as error:
        parser.exit(1, f"Refused: {error}\n")
    print(f"Validated GPT; proposal written to {args.output}. No disk was changed.")


if __name__ == "__main__":
    main()
