from pathlib import Path
import argparse
import json
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from kshimc_image import (
    LINUX_NAME, UEFI_NAME, RAM_IMAGE_LIMIT, PARTITION_BYTES, sha256, stock_kernel, verify_boot,
    verify_ram_linux_boot, verify_ram_uefi_boot, wrap_boot, wrap_ram_linux_boot,
    verify_installed_uefi_boot,
)

parser = argparse.ArgumentParser()
parser.add_argument("stock", type=Path)
parser.add_argument("runtime", type=Path)
parser.add_argument("out", type=Path)
parser.add_argument("--linux", type=Path, help="read-only board kernel; RAM-only output")
parser.add_argument("--uefi", type=Path, help="target RAM UEFI provider, never a QEMU variant")
parser.add_argument("--uefi-dtb", type=Path)
parser.add_argument("--installable", action="store_true",
                    help="partition-sized Android + persistent UEFI menu; defaults to UEFI")
args = parser.parse_args()
if args.linux and args.uefi:
    parser.error("choose one ARM64 payload")
if bool(args.uefi) != bool(args.uefi_dtb):
    parser.error("UEFI provider and DT must be supplied together")
if args.installable and not args.uefi:
    parser.error("--installable requires a UEFI provider")
stock_path, runtime_path, out = args.stock, args.runtime, args.out
stock_hash = "9f7cf9582f4c36b9ba831578b4f1182439a04be813bf277450fab595ae5d9a53"
stock = stock_path.read_bytes()
original = stock_kernel(stock, stock_hash)
runtime = (runtime_path / "kShimC.bin").read_bytes()
linux = None
linux_metadata = None
uefi = None
if args.linux:
    linux = (args.linux / "Image").read_bytes()
    linux_metadata = json.loads((args.linux / "metadata.json").read_text())
    assert linux_metadata["mode"] == "readonly"
    required = {
        "CONFIG_BUILTIN_DTB=y", 'CONFIG_BUILTIN_DTB_NAME="qcom/sm8750-lenovo-elden"',
        "CONFIG_CMDLINE_FORCE=y", "CONFIG_OVERLAY_FS=y",
    }
    assert required <= set((args.linux / "kernel.config").read_text().splitlines())
if args.uefi:
    policy = json.loads((args.uefi / "provider-policy.json").read_text())
    assert policy["scope"] == "unvalidated TB322FC RAM candidate"
    assert "CONFIG_Y700_RAM_LAB=y" not in (args.uefi / ".config").read_text().splitlines()
    assert policy["physical_storage_drivers"] == "absent"
    uefi = (args.uefi / "u-boot.bin").read_bytes()
    dtb = (args.uefi_dtb / "elden.dtb").read_bytes()
    if args.installable:
        media = json.loads((args.uefi / "media.json").read_text())
        assert media["generation"]["root_mode"] == "persistent"
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    (root / "kernel").write_bytes(original)
    packed = root / "packed"
    config = root / "pack.ini"
    default = "Image-01" if args.installable else "Image-00"
    text = (f"[Pack]\nShim = {runtime_path}/kShimC.bin\nOutput = {packed}\n"
            f"Default = {default}\nTimeout = 10000\n\n[Image-00]\nName = Android\n"
            f"Path = {root}/kernel\nType = Linux\nBaseImage = true\nAlign = 21\n")
    if linux is not None:
        text += (f"\n[Image-01]\nName = {LINUX_NAME.decode()}\nPath = {args.linux}/Image\n"
                 "Type = Linux\nAlign = 21\n")
    if uefi is not None:
        text += (f"\n[Image-01]\nName = {UEFI_NAME.decode()}\nPath = {args.uefi}/u-boot.bin\n"
                 "Type = Linux\nAlign = 21\nDeviceTreeBlob = Image-02\n"
                 f"\n[Image-02]\nName = UEFI board DT\nPath = {args.uefi_dtb}/elden.dtb\n"
                 "Type = DTB\nAlign = 3\n")
    config.write_text(text + "\n[Manifest]\nType = Manifest\n")
    subprocess.run(["MultiBootKernelPatcher", str(config)], check=True)
    if args.installable:
        image = wrap_boot(stock, packed.read_bytes())
        layout = verify_installed_uefi_boot(image, stock, runtime, uefi, dtb, stock_hash)
    elif uefi is not None:
        image = wrap_ram_linux_boot(stock, packed.read_bytes())
        layout = verify_ram_uefi_boot(image, stock, runtime, uefi, dtb, stock_hash)
    elif linux is None:
        image = wrap_boot(stock, packed.read_bytes())
        layout = verify_boot(image, stock, runtime, stock_hash)
    else:
        image = wrap_ram_linux_boot(stock, packed.read_bytes())
        layout = verify_ram_linux_boot(image, stock, runtime, linux, stock_hash)
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
if linux is not None:
    metadata.update(scope="RAM-only Android + Linux readonly-overlay; no device acceptance",
                    ram_image_limit_bytes=RAM_IMAGE_LIMIT, flashable=False,
                    linux_sha256=sha256(linux), linux_metadata=linux_metadata)
if uefi is not None:
    media = json.loads((args.uefi / "media.json").read_text())
    metadata.update(scope="RAM-only stock Android + UEFI/systemd-boot",
                    ram_image_limit_bytes=RAM_IMAGE_LIMIT, flashable=False,
                    provider_sha256=sha256(uefi), dtb_sha256=sha256(dtb),
                    provider_policy=policy,
                    provider_media=media)
if args.installable:
    metadata.update(scope="Installable Android + UEFI/systemd-boot with persistent root",
                    flashable=True, partition_bytes=PARTITION_BYTES,
                    default_entry="UEFI", avb_footer="required before installation")
(out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
(out / "SHA256SUMS").write_text(f"{sha256(image)}  boot.img\n")
