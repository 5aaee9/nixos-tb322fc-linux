#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Build an isolated, temporary USB RNDIS + NBD boot image.
set -euo pipefail

PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
export PROJECT
cd "$PROJECT"

# Relative overrides are resolved from the vendor project directory.
ARTIFACT_DIR=${ARTIFACT_DIR:-"$PROJECT/artifacts"}

# Keep the temporary test artifact stable across incremental rebuilds. The
# date is the project build date; callers can override it for a new release.
export KBUILD_BUILD_TIMESTAMP=${KBUILD_BUILD_TIMESTAMP:-"2026-10-23 00:00:00 UTC"}
export KBUILD_BUILD_USER=${KBUILD_BUILD_USER:-codex}
export KBUILD_BUILD_HOST=${KBUILD_BUILD_HOST:-y700-build}

for program in python3 make cc clang ld.lld llvm-ar mkbootimg aarch64-linux-gnu-gcc; do
    command -v "$program" >/dev/null || {
        echo "Missing host tool: $program" >&2
        exit 1
    }
done

export TMPDIR="$PROJECT/build/tmp-usb-nbd"
mkdir -p "$TMPDIR" build/kernel-usb-nbd

FIRMWARE_MANIFEST=${FIRMWARE_MANIFEST:-firmware-tb322fc-prc.json}
FIRMWARE_DIR="$PROJECT/inputs/firmware"
INITRAMFS_LIST=${INITRAMFS_LIST:-configs/initramfs-usb-nbd.list}
export FIRMWARE_MANIFEST FIRMWARE_DIR INITRAMFS_LIST

python3 - <<'PY'
import hashlib
import json
import os
import subprocess
from pathlib import Path

root = Path.cwd()
manifest = root / os.environ["FIRMWARE_MANIFEST"]
data = json.loads(manifest.read_text())
actual_tree = subprocess.check_output(
    ["git", "-C", "sources/kernel", "write-tree"], text=True
).strip()
expected_tree = json.loads((root / "sources.json").read_text())["kernel"]["tree"]
assert actual_tree == expected_tree, "kernel index differs from sources.json"
subprocess.run(["git", "-C", "sources/kernel", "diff", "--exit-code"], check=True)
for item in data["files"]:
    path = root / "inputs/firmware" / item["path"]
    assert path.is_file(), f"Missing firmware: {path}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == item["sha256"], f"Firmware mismatch: {path}"
PY

BUSYBOX="$PROJECT/build/busybox/busybox"
if [[ ! -x "$BUSYBOX" ]]; then
    bash "$PROJECT/scripts/build-boot.sh" initramfs
fi
"$BUSYBOX" --list | grep -qx nbd-client || {
    echo "The BusyBox build does not contain nbd-client" >&2
    exit 1
}

GEN_INIT_CPIO="$PROJECT/build/gen_init_cpio"
if [[ ! -x "$GEN_INIT_CPIO" ]]; then
    cc -O2 -o "$GEN_INIT_CPIO" sources/kernel/usr/gen_init_cpio.c
fi

INITRAMFS_CPIO="$PROJECT/build/initramfs-usb-nbd.cpio"
export BUSYBOX
"$GEN_INIT_CPIO" -t 0 "$INITRAMFS_LIST" > "$INITRAMFS_CPIO"

KERNEL_OUT="$PROJECT/build/kernel-usb-nbd"
KERNEL_CONFIG="$KERNEL_OUT/.config"
cp configs/kernel.config "$KERNEL_CONFIG"
sources/kernel/scripts/config --file "$KERNEL_CONFIG" \
    --enable USB_DWC3_DUAL_ROLE \
    --enable USB_GADGET \
    --enable USB_CONFIGFS_RNDIS \
    --enable BLK_DEV_NBD \
    --set-str CMDLINE "$(cat configs/cmdline-usb-nbd.txt)" \
    --set-str INITRAMFS_SOURCE "$INITRAMFS_CPIO" \
    --set-str EXTRA_FIRMWARE_DIR "$FIRMWARE_DIR"

# The rootfs has no matching module tree, so firewall requirements must
# remain built in after Kconfig resolves their dependencies.
NETWORKING_REQUIRED=()
while IFS= read -r setting || [[ -n "$setting" ]]; do
    [[ -z "$setting" || "$setting" == \#* ]] && continue
    if [[ ! "$setting" =~ ^CONFIG_[A-Z0-9_]+=y$ ]]; then
        echo "Expected a built-in option in kernel-networking.config: $setting" >&2
        exit 1
    fi
    NETWORKING_REQUIRED+=("$setting")
    sources/kernel/scripts/config --file "$KERNEL_CONFIG" \
        --enable "${setting%%=*}"
done < configs/kernel-networking.config

make -C sources/kernel O="$KERNEL_OUT" ARCH=arm64 LLVM=1 olddefconfig
for expected in \
    CONFIG_USB_DWC3_DUAL_ROLE=y \
    CONFIG_USB_GADGET=y \
    CONFIG_USB_CONFIGFS_RNDIS=y \
    CONFIG_BLK_DEV_NBD=y \
    CONFIG_CMDLINE_FORCE=y \
    CONFIG_OVERLAY_FS=y \
    "${NETWORKING_REQUIRED[@]}"; do
    grep -Fqx "$expected" "$KERNEL_CONFIG" || {
        echo "Kernel configuration did not retain $expected" >&2
        exit 1
    }
done
grep -Fqx "CONFIG_CMDLINE=\"$(cat configs/cmdline-usb-nbd.txt)\"" "$KERNEL_CONFIG" || {
    echo "Built-in command line differs from the USB/NBD boot header" >&2
    exit 1
}

make -C sources/kernel O="$KERNEL_OUT" ARCH=arm64 LLVM=1 \
    -j"${JOBS:-12}" Image qcom/sm8750-lenovo-elden.dtb

mkdir -p "$ARTIFACT_DIR"
IMAGE="$ARTIFACT_DIR/Image-usb-nbd"
DTB="$ARTIFACT_DIR/sm8750-lenovo-elden-usb-nbd.dtb"
CONFIG="$ARTIFACT_DIR/kernel-usb-nbd.config"
BOOT="$ARTIFACT_DIR/boot-usb-nbd.img"
cp "$KERNEL_OUT/arch/arm64/boot/Image" "$IMAGE"
cp "$KERNEL_OUT/arch/arm64/boot/dts/qcom/sm8750-lenovo-elden.dtb" "$DTB"
cp "$KERNEL_CONFIG" "$CONFIG"

: > build/empty-ramdisk
mkbootimg --header_version 4 \
    --kernel "$IMAGE" \
    --ramdisk build/empty-ramdisk \
    --os_version 15.0.0 \
    --os_patch_level 2026-08 \
    --cmdline "$(cat configs/cmdline-usb-nbd.txt)" \
    --output "$BOOT"

(cd "$ARTIFACT_DIR" && sha256sum \
    Image-usb-nbd \
    sm8750-lenovo-elden-usb-nbd.dtb \
    kernel-usb-nbd.config \
    boot-usb-nbd.img > USB-NBD-SHA256SUMS)

echo "Built $BOOT."
echo "Test only with fastboot boot; do not flash or erase any partition."
