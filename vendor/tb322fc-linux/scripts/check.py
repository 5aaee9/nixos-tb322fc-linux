#!/usr/bin/env python3
"""Check the public repository for stale labels, local paths and broken inputs."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    names = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-z"], text=True).split("\0")
    files = [ROOT / name for name in names if name and (ROOT / name).is_file()]
    failures = []
    experiment = re.compile(r"\b[Vv][0-9]{2,}[a-z][a-z0-9-]*\b")
    local_path = re.compile(r"/home/[A-Za-z0-9_-]+/|\.\./(?:build|artifacts|linux-elden)/")
    for path in files:
        text = path.read_text()
        relative = str(path.relative_to(ROOT))
        if experiment.search(relative) or experiment.search(text):
            failures.append(f"experiment label: {relative}")
        if local_path.search(text):
            failures.append(f"private workspace path: {relative}")
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if "://" in target or target.startswith("#"):
                    continue
                if not (path.parent / target.split("#")[0]).exists():
                    failures.append(f"broken link: {relative}: {target}")
            for block in re.findall(r"```sh\n(.*?)```", text, re.S):
                subprocess.run(["bash", "-n"], input=block, text=True, check=True)
    sources = json.loads((ROOT / "sources.json").read_text())
    for name, source in sources.items():
        assert source["url"].startswith("https://"), name
        assert re.fullmatch(r"[0-9a-f]{40}", source["commit"]), name
        assert re.fullmatch(r"[0-9a-f]{40}", source["tree"]), name
        if source.get("patch"):
            assert (ROOT / source["patch"]).is_file(), name
    firmware = json.loads((ROOT / "firmware.json").read_text())["files"]
    assert len({item["path"] for item in firmware}) == len(firmware)
    for item in firmware:
        path = Path(item["path"])
        assert not path.is_absolute() and ".." not in path.parts
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
        assert item["size"] > 0
    subprocess.run(["sh", "-n", str(ROOT / "initramfs/init")], check=True)
    subprocess.run(["bash", "-n", str(ROOT / "scripts/build-boot.sh")], check=True)
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Checked {len(files)} tracked files, {len(sources)} sources and {len(firmware)} firmware entries")


if __name__ == "__main__":
    main()
