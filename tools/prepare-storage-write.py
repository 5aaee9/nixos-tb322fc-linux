#!/usr/bin/env python3
"""Prepare an exact GPT transaction from a private snapshot; CLI never opens disks."""
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import uuid
import zlib

spec = importlib.util.spec_from_file_location(
    "storage_layout", Path(__file__).with_name("storage-layout.py"))
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)
ORDER = ("backup_entries", "backup_header", "primary_entries", "primary_header")


def region(value, offset):
    digest = hashlib.sha256(value).hexdigest()
    return dict(offset=offset, base64=base64.b64encode(value).decode(),
                sha256=digest, readback_sha256=digest)


def bytes_of(record):
    return base64.b64decode(record["base64"], validate=True)


def prepare(capture, budget, new_guids=None):
    proposal = layout.plan(capture, budget)
    header, partitions = layout.decode_capture(capture)
    guids = [str(uuid.uuid4()), str(uuid.uuid4())] if new_guids is None else new_guids
    layout.require(len(guids) == 2, "two new GUIDs required")
    identities = {uuid.UUID(p["guid"]) for p in partitions}
    parsed = [uuid.UUID(g) for g in guids]
    layout.require(len(set(parsed)) == 2 and all(g.int and g not in identities for g in parsed),
                   "new partition GUIDs must be unique and nonzero")
    after = copy.deepcopy(capture)
    table = bytearray(bytes_of(capture["regions"]["primary_entries"]))
    stride = header["entry_size"]
    userdata_at = (proposal["userdata"]["number"] - 1) * stride
    struct.pack_into("<Q", table, userdata_at + 40,
                     proposal["userdata"]["proposed_end_lba"])
    allowed = set(range(userdata_at + 40, userdata_at + 48))
    for partition, guid in zip(proposal["new_partitions"], parsed):
        offset = (partition["number"] - 1) * stride
        layout.require(not any(table[offset:offset + stride]), "new entry is not empty")
        table[offset:offset + 16] = uuid.UUID(partition["type"]).bytes_le
        table[offset + 16:offset + 32] = guid.bytes_le
        struct.pack_into("<QQQ", table, offset + 32, partition["start"], partition["end"], 0)
        name = partition["label"].encode("utf-16-le")
        table[offset + 56:offset + 56 + len(name)] = name
        allowed.update(range(offset, offset + stride))
    old_table = bytes_of(capture["regions"]["primary_entries"])
    layout.require(all(a == b or n in allowed for n, (a, b) in enumerate(zip(old_table, table))),
                   "unexpected entry-array difference")
    for name in ("primary_entries", "backup_entries"):
        after["regions"][name] = region(table, capture["regions"][name]["offset"])
    for name in ("primary_header", "backup_header"):
        old = bytes_of(capture["regions"][name])
        raw = bytearray(old)
        struct.pack_into("<I", raw, 88, zlib.crc32(table))
        struct.pack_into("<I", raw, 16, 0)
        header_size = struct.unpack_from("<I", raw, 12)[0]
        struct.pack_into("<I", raw, 16, zlib.crc32(raw[:header_size]))
        layout.require(all(a == b or n in set(range(16, 20)) | set(range(88, 92))
                           for n, (a, b) in enumerate(zip(old, raw))),
                       "unexpected header difference")
        after["regions"][name] = region(raw, capture["regions"][name]["offset"])
    checked_header, checked_parts = layout.decode_capture(after)
    for key in header:
        if key != "table_crc":
            layout.require(checked_header[key] == header[key], "GPT geometry changed")
    layout.require(len(checked_parts) == len(partitions) + 2, "partition count changed")
    return {
        "schema": 1, "scope": "GPT only; does not resize or recreate Android filesystems",
        "linux_budget_gib": budget, "new_guids": [str(g) for g in parsed],
        "proposal": proposal, "before": capture, "after": after,
        "write_order": list(ORDER),
    }


def validate_transaction(transaction):
    layout.require(transaction.get("schema") == 1, "transaction schema")
    expected = prepare(transaction["before"], transaction["linux_budget_gib"],
                       transaction["new_guids"])
    layout.require(transaction == expected, "transaction differs from derived allowed changes")


def assert_snapshot(fd, capture):
    for name, record in capture["regions"].items():
        expected = bytes_of(record)
        actual = os.pread(fd, len(expected), record["offset"])
        layout.require(actual == expected, f"live {name} differs from snapshot")


def apply_to_fd(fd, transaction, checkpoint=None):
    """Caller must verify live identity/unmounted state before supplying a writable fd."""
    validate_transaction(transaction)
    assert_snapshot(fd, transaction["before"])
    # At each interruption boundary at least one whole GPT copy stays valid.
    for name in ORDER:
        record = transaction["after"]["regions"][name]
        value = bytes_of(record)
        done = 0
        while done < len(value):
            written = os.pwrite(fd, value[done:], record["offset"] + done)
            if written <= 0:
                raise OSError("short GPT write")
            done += written
        os.fsync(fd)
        layout.require(os.pread(fd, len(value), record["offset"]) == value,
                       f"{name} write readback mismatch; do not reboot")
        if checkpoint is not None:
            checkpoint(name)
    assert_snapshot(fd, transaction["after"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--linux-gib", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    transaction = prepare(json.loads(args.snapshot.read_text()), args.linux_gib)
    validate_transaction(transaction)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(transaction, stream, indent=2)
        stream.write("\n")
    print(f"Prepared verified GPT bytes: {args.output}. No disk opened or changed.")


if __name__ == "__main__":
    main()
