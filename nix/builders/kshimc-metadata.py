from pathlib import Path
import hashlib
import json
import os
import sys

build, out, patches, lock = map(Path, sys.argv[1:])
runtime = (out / "kShimC.bin").read_bytes()
assert len(runtime) == 4 * 1024**2 and b"tb322fc-diag-v1;" in runtime
files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(out.iterdir()) if p.is_file()}
crdk = {str(p.relative_to(build / "ports/crdk/source")):
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((build / "ports/crdk/source").rglob("*")) if p.is_file()}
metadata = {
    "schema": 1, "scope": "Nix-built diagnostic, no device acceptance",
    "sources": json.loads((patches / "sources.json").read_text()),
    "actual_inputs": json.loads(os.environ["Y700_SOURCE_INPUTS"]),
    "flake_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
    "files": files,
    "compiled_crdk_sha256": hashlib.sha256(json.dumps(crdk, sort_keys=True).encode()).hexdigest(),
    "menu_limit_ms": 20000, "hard_lock_recovery": False,
}
(out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
(out / "SHA256SUMS").write_text("".join(f"{v}  {k}\n" for k, v in files.items()))
