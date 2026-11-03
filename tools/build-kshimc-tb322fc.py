#!/usr/bin/env python3
"""Compatibility entry point for the pinned Nix kShimC diagnostic."""
import argparse
import hashlib
from pathlib import Path
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
STOCK_HASH = "9f7cf9582f4c36b9ba831578b4f1182439a04be813bf277450fab595ae5d9a53"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-boot", type=Path)
    parser.add_argument("--stock-sha256")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=12)
    args = parser.parse_args()
    if args.out.exists() or args.out.is_symlink():
        parser.error("output link must be new")
    if args.jobs < 1:
        parser.error("jobs must be positive")
    if args.stock_boot:
        if args.stock_sha256 != STOCK_HASH:
            parser.error("stock-sha256 must match the verified own-tablet .229 backup")
        with args.stock_boot.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != STOCK_HASH:
                parser.error("stock boot hash mismatch")
        subprocess.run(["nix", "run", "--extra-experimental-features", "nix-command flakes",
                        str(PROJECT) + "#import-device-inputs", "--", "--stock-boot",
                        str(args.stock_boot.resolve())], check=True)
    elif args.stock_sha256:
        parser.error("stock-sha256 requires stock-boot")
    subprocess.run(["bash", str(PROJECT / "tools/build-artifact.sh"), "boot-kshimc",
                    str(args.out.absolute()), "--cores", str(args.jobs)], check=True)


if __name__ == "__main__":
    main()
