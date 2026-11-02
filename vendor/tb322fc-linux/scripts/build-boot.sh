#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
export PROJECT
cd "$PROJECT"
mode=${1:-all}
[[ "$mode" == all || "$mode" == initramfs ]] || { echo "Usage: $0 [all|initramfs]" >&2; exit 2; }
export TMPDIR="$PROJECT/build/tmp"
mkdir -p "$TMPDIR"
for program in python3 make cc curl tar aarch64-linux-gnu-gcc; do
    command -v "$program" >/dev/null || { echo "Missing host tool: $program" >&2; exit 1; }
done
python3 - <<'PY'
import hashlib, json, subprocess
import os
from pathlib import Path
r = Path.cwd()
source = json.loads((r / 'sources.json').read_text())['kernel']
actual = subprocess.check_output(['git', '-C', 'sources/kernel', 'write-tree'], text=True).strip()
assert actual == source['tree'], 'kernel index differs from sources.json'
subprocess.run(['git', '-C', 'sources/kernel', 'diff', '--exit-code'], check=True)
manifest = r / os.environ.get('FIRMWARE_MANIFEST', 'firmware.json')
for item in json.loads(manifest.read_text())['files']:
    path = r / 'inputs/firmware' / item['path']
    assert path.is_file(), f'Missing firmware: {path}; run scripts/import-firmware.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], f'Firmware mismatch: {path}'
PY

# BusyBox is built from public source; no private binary payload is required.
archive=build/busybox-1.36.1.tar.bz2
if [[ ! -f "$archive" ]]; then
    curl --fail --location --output "$archive.part" \
        https://busybox.net/downloads/busybox-1.36.1.tar.bz2
    mv "$archive.part" "$archive"
fi
echo "b8cc24c9574d809e7279c3be349795c5d5ceb6fdf19ca709f80cde50e47de314  $archive" | sha256sum -c -
if [[ ! -d sources/busybox ]]; then
    mkdir -p sources/busybox
    tar -xf "$archive" -C sources/busybox --strip-components=1
fi
mkdir -p build/busybox
cp configs/busybox.config build/busybox/.config
make -C sources/busybox O="$PROJECT/build/busybox" ARCH=arm64 \
    CROSS_COMPILE=aarch64-linux-gnu- oldconfig </dev/null
make -C sources/busybox O="$PROJECT/build/busybox" ARCH=arm64 \
    CROSS_COMPILE=aarch64-linux-gnu- -j"${JOBS:-12}" busybox
export BUSYBOX="$PROJECT/build/busybox/busybox"
export FIRMWARE_DIR="$PROJECT/inputs/firmware"
cc -O2 -o build/gen_init_cpio sources/kernel/usr/gen_init_cpio.c
INITRAMFS_LIST=${INITRAMFS_LIST:-configs/initramfs.list}
build/gen_init_cpio -t 0 "$INITRAMFS_LIST" > build/initramfs.cpio
[[ "$mode" == all ]] || exit 0

for program in clang ld.lld llvm-ar mkbootimg; do
    command -v "$program" >/dev/null || { echo "Missing host tool: $program" >&2; exit 1; }
done
mkdir -p build/kernel artifacts
cp configs/kernel.config build/kernel/.config
sources/kernel/scripts/config --file build/kernel/.config \
    --set-str INITRAMFS_SOURCE "$PROJECT/build/initramfs.cpio" \
    --set-str EXTRA_FIRMWARE_DIR "$FIRMWARE_DIR"
make -C sources/kernel O="$PROJECT/build/kernel" ARCH=arm64 LLVM=1 olddefconfig
make -C sources/kernel O="$PROJECT/build/kernel" ARCH=arm64 LLVM=1 \
    -j"${JOBS:-12}" Image qcom/sm8750-lenovo-elden.dtb
cp build/kernel/arch/arm64/boot/Image artifacts/Image
cp build/kernel/arch/arm64/boot/dts/qcom/sm8750-lenovo-elden.dtb artifacts/sm8750-lenovo-elden.dtb
cp build/kernel/.config artifacts/kernel.config
: > build/empty-ramdisk
mkbootimg --header_version 4 --kernel artifacts/Image --ramdisk build/empty-ramdisk \
    --os_version 15.0.0 --os_patch_level 2026-08 \
    --cmdline "$(cat configs/cmdline.txt)" --output artifacts/boot.img
(cd artifacts && sha256sum Image sm8750-lenovo-elden.dtb kernel.config boot.img > SHA256SUMS)
echo "Built artifacts/boot.img. Test only with fastboot boot; do not flash it."
