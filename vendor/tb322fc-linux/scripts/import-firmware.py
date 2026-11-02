#!/usr/bin/env python3
"""Find the required firmware by checksum in extracted stock firmware trees."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / os.environ.get("FIRMWARE_MANIFEST", "firmware.json"),
        help="Firmware manifest relative to the project root",
    )
    parser.add_argument("directories", nargs="+", type=Path,
                        help="Extracted Android firmware and generated audio topology")
    args = parser.parse_args()
    manifest = args.manifest
    if not manifest.is_absolute():
        manifest = ROOT / manifest
    rows = json.loads(manifest.read_text())["files"]
    sizes = {row["size"] for row in rows}
    required = {row["sha256"] for row in rows}
    found = {}
    for directory in args.directories:
        if not directory.is_dir():
            parser.error(f"not a directory: {directory}")
        for path in directory.rglob("*"):
            if path.is_file() and path.stat().st_size in sizes:
                checksum = digest(path)
                if checksum in required:
                    found[checksum] = path
    missing = [row["path"] for row in rows if row["sha256"] not in found]
    if missing:
        raise SystemExit("Missing matching firmware (nothing imported):\n" + "\n".join(missing))
    output = ROOT / "inputs" / "firmware"
    # Check conflicts before copying anything; never replace a different payload.
    for row in rows:
        target = output / row["path"]
        if target.exists() and digest(target) != row["sha256"]:
            raise SystemExit(f"existing firmware differs: {target}")
    for row in rows:
        target = output / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(found[row["sha256"]], target)
    print(f"Verified and staged {len(rows)} firmware files in {output}")


if __name__ == "__main__":
    main()
