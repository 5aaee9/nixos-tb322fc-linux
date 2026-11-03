"""Record the exact Nix inputs of the offline, dummy-signed ABL experiment."""
from pathlib import Path
import hashlib
import json
import os
import struct
import sys

source, patches, output = map(Path, sys.argv[1:4])
probe = sys.argv[4] == "1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


menu = (output / "openabl-menu.efi").read_bytes()
assert menu[:2] == b"MZ"
pe = struct.unpack_from("<I", menu, 0x3C)[0]
assert menu[pe:pe + 4] == b"PE\0\0"
assert struct.unpack_from("<H", menu, pe + 4)[0] == 0xAA64
for name in ("abl-unsigned-sm8750.elf", "abl-dummy-signed-sm8750.elf"):
    data = (output / name).read_bytes()
    assert data[:4] == b"\x7fELF" and 0 < len(data) <= 1048576
metadata = {
    "schema": 1,
    "scope": "offline experiment; not OEM authenticated; do not flash",
    "actual_inputs": json.loads(os.environ["Y700_SOURCE_INPUTS"]),
    "entry_probe": probe,
    "features": ["park-display", "sysfont"],
    "signature": "qtestsign MBNv7 dummy signature, not OEM authentication",
    "patches": {p.name: digest(p) for p in sorted(patches.glob("*.patch"))},
    "upstream_patch_sha256": digest(source / "Abl/openabl.patch"),
    "overlay": {str(p.relative_to(source / "Abl")): digest(p)
                for p in sorted((source / "Abl/QcomModulePkg").rglob("*")) if p.is_file()},
    "files": {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
}
(output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
