from pathlib import Path
import hashlib
import json
import os
import struct
import sys

out, vendor = map(Path, sys.argv[1:3])
mode = sys.argv[3]
image = (out / "Image").read_bytes()
assert image[56:60] == b"ARM\x64"
if mode == "efi":
    pe = struct.unpack_from("<I", image, 0x3C)[0]
    assert image[:2] == b"MZ" and image[pe:pe+4] == b"PE\0\0"
    assert struct.unpack_from("<H", image, pe + 4)[0] == 0xAA64
files = {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
         for name in ("Image", "elden.dtb", "kernel.config", "kernel.release", "cmdline.txt")}
metadata = {
    "schema": 1, "scope": "Nix offline board kernel; no device acceptance", "mode": mode,
    "kernel": json.loads((vendor / "sources.json").read_text())["kernel"],
    "actual_inputs": json.loads(os.environ["Y700_SOURCE_INPUTS"]),
    "patches": {str(p.relative_to(vendor)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((vendor / "patches/kernel").glob("*.patch"))},
    "release": (out / "kernel.release").read_text().strip(), "files": files,
}
(out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
(out / "SHA256SUMS").write_text("".join(f"{v}  {k}\n" for k, v in files.items()))
