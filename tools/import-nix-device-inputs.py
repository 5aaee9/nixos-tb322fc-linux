#!/usr/bin/env python3
"""Import only verified firmware and stock boot bytes; never open a device."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
FIRMWARE_HASH = "3b3e61e83579f1a325fe629b8e7f7bd8603654cfe725a2cb89564e0e3d038097"
STOCK_HASH = "9f7cf9582f4c36b9ba831578b4f1182439a04be813bf277450fab595ae5d9a53"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def firmware_files(directory):
    manifest = json.loads((PROJECT / "vendor/tb322fc-linux/firmware-tb322fc-prc.json").read_text())
    files = sorted(manifest["files"], key=lambda x: x["path"])
    if len(files) != 78 or len({f["path"] for f in files}) != 78:
        raise ValueError("Expected 78 distinct firmware files")
    for item in files:
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe firmware path")
        path = directory / relative
        if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
            raise ValueError("Firmware mismatch: " + item["path"])
    return files


def arrange_firmware(directories, output):
    manifest = json.loads((PROJECT / "vendor/tb322fc-linux/firmware-tb322fc-prc.json").read_text())
    rows = manifest["files"]
    sizes = {row["size"] for row in rows}
    required = {row["sha256"] for row in rows}
    found = {}
    for directory in directories:
        if not directory.is_dir():
            raise ValueError("Not a firmware source directory: " + str(directory))
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.stat().st_size in sizes:
                checksum = digest(path)
                if checksum in required:
                    found[checksum] = path
    missing = [row["path"] for row in rows if row["sha256"] not in found]
    if missing:
        raise ValueError("Missing matching firmware: " + ", ".join(missing))
    for row in rows:
        target = output / row["path"]
        relative = PurePosixPath(row["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe firmware path")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(found[row["sha256"]], target)
    firmware_files(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path)
    parser.add_argument("--stock-boot", type=Path)
    parser.add_argument("--verify-firmware", type=Path)
    parser.add_argument("--stock-directory", action="append", type=Path,
                        help="Search a private extracted stock tree by manifest hashes")
    parser.add_argument("--generated-directory", action="append", type=Path, default=[],
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.verify_firmware:
        firmware_files(args.verify_firmware)
        print("Verified 78 matching firmware files")
        return
    if not args.firmware and not args.stock_boot and not args.stock_directory:
        parser.error("provide --firmware, --stock-directory and/or --stock-boot")
    if args.firmware and args.stock_directory:
        parser.error("choose arranged --firmware or raw --stock-directory")
    with tempfile.TemporaryDirectory(prefix="y700-nix-inputs-") as temporary:
        directory = Path(temporary)
        if args.stock_directory:
            args.firmware = arrange_firmware(
                args.stock_directory + args.generated_directory, directory / "firmware")
        imports = []
        if args.firmware:
            files = firmware_files(args.firmware)
            archive = directory / "tb322fc-229-firmware.tar"
            with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as tar:
                for item in files:
                    path = args.firmware / item["path"]
                    entry = tarfile.TarInfo(item["path"])
                    entry.size, entry.mode, entry.mtime = path.stat().st_size, 0o444, 0
                    with path.open("rb") as stream:
                        tar.addfile(entry, stream)
            if digest(archive) != FIRMWARE_HASH:
                raise ValueError("Canonical firmware archive hash mismatch")
            imports.append(archive)
        if args.stock_boot:
            target = directory / "tb322fc-229-stock-boot.img"
            shutil.copyfile(args.stock_boot, target)
            if target.stat().st_size != 96 * 1024**2 or digest(target) != STOCK_HASH:
                raise ValueError("Not the verified own-tablet .229 stock boot")
            imports.append(target)
        for path in imports:
            subprocess.run(["nix-store", "--add-fixed", "sha256", str(path)], check=True)


if __name__ == "__main__":
    main()
