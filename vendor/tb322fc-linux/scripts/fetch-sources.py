#!/usr/bin/env python3
"""Fetch pinned public sources and apply the bundled device support patches."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def main():
    manifest = json.loads((ROOT / "sources.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("components", nargs="*", help="Default: all components")
    args = parser.parse_args()
    for name in args.components or manifest:
        if name not in manifest:
            parser.error(f"unknown component: {name}")
        source = manifest[name]
        if "patch" in source and "patches" in source:
            parser.error(f"{name}: use either patch or patches, not both")
        patches = source.get(
            "patches", [source["patch"]] if source.get("patch") else [])
        if not isinstance(patches, list) or any(
                not isinstance(patch, str) for patch in patches):
            parser.error(f"{name}: patches must be an ordered list of paths")
        for patch in patches:
            if not (ROOT / patch).is_file():
                parser.error(f"{name}: missing patch: {patch}")
        destination = ROOT / "sources" / name
        if destination.exists():
            raise SystemExit(f"{destination} already exists; preserve or remove it explicitly")
        destination.mkdir(parents=True)
        print(f"Fetching {name} at {source['commit']}", flush=True)
        git(destination, "init", "--quiet")
        git(destination, "remote", "add", "origin", source["url"])
        git(destination, "fetch", "--quiet", "--depth=1", "origin", source["commit"])
        git(destination, "checkout", "--quiet", "--detach", "FETCH_HEAD")
        if source.get("base_tree") and (
                git(destination, "rev-parse", "HEAD^{tree}") != source["base_tree"]):
            raise SystemExit(f"{name}: upstream tree does not match sources.json")
        for patch in patches:
            git(destination, "apply", "--index", str(ROOT / patch))
        if git(destination, "write-tree") != source["tree"]:
            raise SystemExit(f"{name}: source tree does not match sources.json")
        print(f"Verified {name}: {source['tree']}", flush=True)


if __name__ == "__main__":
    main()
