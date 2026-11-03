from pathlib import Path
import json
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from kshimc_image import sha256, stock_kernel, verify_boot, wrap_boot

stock_path, runtime_path, out = map(Path, sys.argv[1:])
stock_hash = "9f7cf9582f4c36b9ba831578b4f1182439a04be813bf277450fab595ae5d9a53"
stock = stock_path.read_bytes()
original = stock_kernel(stock, stock_hash)
runtime = (runtime_path / "kShimC.bin").read_bytes()
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root / "kernel").write_bytes(original)
    packed = root / "packed"
    config = root / "pack.ini"
    config.write_text(f"[Pack]\nShim = {runtime_path}/kShimC.bin\nOutput = {packed}\n"
                      "Default = Image-00\nTimeout = 10000\n\n[Image-00]\nName = Android\n"
                      f"Path = {root}/kernel\nType = Linux\nBaseImage = true\nAlign = 21\n"
                      "\n[Manifest]\nType = Manifest\n")
    subprocess.run(["MultiBootKernelPatcher", str(config)], check=True)
    image = wrap_boot(stock, packed.read_bytes())
    layout = verify_boot(image, stock, runtime, stock_hash)
    subprocess.run(["UnpackTool", str(packed), str(root / "unpacked")], check=True)
    assert (root / "unpacked/BaseImage").read_bytes() == original
out.mkdir()
(out / "boot.img").write_bytes(image)
metadata = {
    "schema": 1, "scope": "RAM-only Android-base diagnostic; no device acceptance",
    "stock_sha256": stock_hash, "runtime_sha256": sha256(runtime),
    "boot_sha256": sha256(image), "boot_bytes": len(image), "layout": layout,
    "runtime_metadata": json.loads((runtime_path / "metadata.json").read_text()),
}
(out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
(out / "SHA256SUMS").write_text(f"{sha256(image)}  boot.img\n")
