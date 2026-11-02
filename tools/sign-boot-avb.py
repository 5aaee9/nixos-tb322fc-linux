#!/usr/bin/env python3
"""Sign a temporary boot image using metadata from a stock AVB template.

The private key and stock template stay outside this project. This helper only
creates a new host-side image; it never talks to fastboot or writes a device.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tool_command(tool: Path, *args: str) -> list[str]:
    if tool.suffix == ".py":
        return [sys.executable, str(tool), *args]
    return [str(tool), *args]


def avb_info(tool: Path, image: Path) -> str:
    result = subprocess.run(
        tool_command(tool, "info_image", "--image", str(image)),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def field(text: str, pattern: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"stock template has no {label}")
    return match.group(1)


def props(text: str) -> list[str]:
    result = []
    for key, value in re.findall(
        r"^\s+Prop:\s+(\S+)\s+->\s+'([^']*)'$", text, re.MULTILINE
    ):
        result.append(f"{key}:{value}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--avbtool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    for path in (args.input, args.template, args.key, args.avbtool):
        if not path.is_file():
            parser.error(f"missing file: {path}")
    if args.input.stat().st_size >= args.template.stat().st_size:
        parser.error("input image must be smaller than the stock partition image")

    template_text = avb_info(args.avbtool, args.template)
    partition_name = field(
        template_text, r"^\s+Partition Name:\s+(\S+)$", "partition name"
    )
    if partition_name != "boot":
        parser.error(f"template partition is {partition_name!r}, expected 'boot'")
    partition_size = int(
        field(template_text, r"^Image size:\s+(\d+) bytes$", "partition size")
    )
    rollback_index = field(
        template_text, r"^Rollback Index:\s+(\d+)$", "rollback index"
    )
    algorithm = field(template_text, r"^Algorithm:\s+(\S+)$", "algorithm")
    salt = field(
        template_text,
        r"^\s+Salt:\s+([0-9a-fA-F]+)$",
        "hash salt",
    )
    expected_key_sha1 = field(
        template_text,
        r"^Public key \(sha1\):\s+([0-9a-fA-F]+)$",
        "public key fingerprint",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.input, args.output)
    command = tool_command(
        args.avbtool,
        "add_hash_footer",
        "--image",
        str(args.output),
        "--partition_name",
        partition_name,
        "--partition_size",
        str(partition_size),
        "--rollback_index",
        rollback_index,
        "--salt",
        salt,
        "--algorithm",
        algorithm,
        "--key",
        str(args.key),
    )
    for prop in props(template_text):
        command.extend(("--prop", prop))
    subprocess.run(command, check=True)

    signed_text = avb_info(args.avbtool, args.output)
    signed_size = int(
        field(signed_text, r"^Image size:\s+(\d+) bytes$", "signed image size")
    )
    original_size = int(
        field(
            signed_text,
            r"^Original image size:\s+(\d+) bytes$",
            "original image size",
        )
    )
    signed_key_sha1 = field(
        signed_text,
        r"^Public key \(sha1\):\s+([0-9a-fA-F]+)$",
        "signed public key fingerprint",
    )
    if signed_size != partition_size:
        parser.error(
            f"signed image is {signed_size} bytes, expected {partition_size}"
        )
    if original_size != args.input.stat().st_size:
        parser.error(
            f"footer records {original_size} input bytes, "
            f"expected {args.input.stat().st_size}"
        )
    if signed_key_sha1.lower() != expected_key_sha1.lower():
        parser.error(
            f"signed key fingerprint {signed_key_sha1} does not match "
            f"template {expected_key_sha1}"
        )

    print(f"input_sha256={sha256(args.input)}")
    print(f"template_sha256={sha256(args.template)}")
    print(f"output_sha256={sha256(args.output)}")
    print(f"output_bytes={args.output.stat().st_size}")
    print(f"partition_name={partition_name}")
    print(f"partition_size={partition_size}")
    print(f"rollback_index={rollback_index}")
    print(f"algorithm={algorithm}")
    print(f"public_key_sha1={signed_key_sha1.lower()}")
    print(f"salt={salt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
