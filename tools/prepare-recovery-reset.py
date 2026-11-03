#!/usr/bin/env python3
"""Prepare a stock-recovery reset request from a private misc backup; no disk I/O."""
import argparse
import os
from pathlib import Path
import struct


def prepare(misc, *, keep_memtag=False):
    if len(misc) < 65536 or len(misc) % 4096:
        raise ValueError("misc backup must contain aligned BCB and system-space regions")
    command = misc[:32].split(b"\0", 1)[0]
    if command not in (b"", b"bootonce-bootloader"):
        raise ValueError("unexpected pending bootloader command")
    if any(misc[64:864]):
        raise ValueError("pending recovery arguments or multistage operation")
    version, magic, merge_status, _ = struct.unpack_from("<BIBB", misc, 32768)
    if version != 2 or magic != 0x56740AB0 or merge_status != 0:
        raise ValueError("Virtual A/B state is not the verified idle v2 format")
    options = b"recovery\n--wipe_data\n--reason=y700_linux_install\n"
    if keep_memtag:
        options += b"--keep_memtag_mode\n"
    result = bytearray(misc)
    result[:32] = b"boot-recovery".ljust(32, b"\0")
    result[64:832] = options.ljust(768, b"\0")
    # Preserve status, stage, vendor boot control and every later misc byte.
    assert result[32:64] == misc[32:64] and result[832:] == misc[832:]
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keep-memtag", action="store_true")
    args = parser.parse_args()
    result = prepare(args.backup.read_bytes(), keep_memtag=args.keep_memtag)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(result)
    print("Prepared private reset request; no tablet or block device accessed.")


if __name__ == "__main__":
    main()
