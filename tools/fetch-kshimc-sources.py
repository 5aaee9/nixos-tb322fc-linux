#!/usr/bin/env python3
"""Fetch immutable kShimC build inputs; never run upstream device scripts."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT / "vendor/tb322fc-linux/patches/kshimc/sources.json"


def fetch(name, entry, cache, runtime_source):
    destination = cache / name
    destination.mkdir(parents=True, exist_ok=True)
    if not (destination / ".git").exists():
        if any(destination.iterdir()):
            raise ValueError(f"Refusing a nonempty source directory: {destination}")
        subprocess.run(["git", "init", "-q", str(destination)], check=True)
        subprocess.run(
            ["git", "-C", str(destination), "remote", "add", "origin", entry["repository"]],
            check=True,
        )
    remote = subprocess.check_output(
        ["git", "-C", str(destination), "remote", "get-url", "origin"], text=True
    ).strip()
    if remote != entry["repository"]:
        raise ValueError(f"Source origin mismatch: {name}")
    result = subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        if result.stdout.strip() != entry["revision"]:
            raise ValueError(f"Refusing to replace a different source revision: {name}")
    else:
        origin = str(runtime_source) if name == "runtime" and runtime_source else "origin"
        subprocess.run(
            ["git", "-C", str(destination), "fetch", "--depth=1", origin, entry["revision"]],
            check=True, timeout=600,
        )
        subprocess.run(
            ["git", "-C", str(destination), "checkout", "--detach", entry["revision"]],
            check=True,
        )
    subprocess.run(
        ["git", "-C", str(destination), "diff", "--exit-code", "HEAD", "--"],
        check=True, capture_output=True,
    )
    extra = subprocess.check_output(
        ["git", "-C", str(destination), "ls-files", "--others", "--exclude-standard"],
        text=True,
    )
    if extra.strip():
        raise ValueError(f"Unexpected source additions: {name}")
    print(f"{name}: {entry['revision']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache", type=Path, default=PROJECT / "vendor/tb322fc-linux/sources/kshimc"
    )
    parser.add_argument("--runtime-source", type=Path, help="Optional existing pinned Git checkout")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    entries = {"runtime": manifest["runtime"], **manifest["dependencies"]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [
            pool.submit(fetch, name, entry, args.cache.resolve(), args.runtime_source)
            for name, entry in entries.items()
        ]
        failures = []
        for job in jobs:
            try:
                job.result()
            except Exception as error:
                failures.append(str(error))
        if failures:
            raise RuntimeError("\n".join(failures))


if __name__ == "__main__":
    main()
