#!/usr/bin/env bash
# Collect only stock firmware paths from the connected user's tablet.
#
# This script never invokes fastboot and never writes an Android partition.
# Some files require a root-capable adb daemon on the tablet.
set -euo pipefail

PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
REF="$PROJECT/vendor/tb322fc-linux"
OUT="${1:-$REF/inputs/stock}"
SERIAL="${ADB_SERIAL:-}"

if ! command -v adb >/dev/null; then
    echo "Missing host tool: adb" >&2
    exit 1
fi
if [[ -n "$SERIAL" ]]; then
    ADB=(adb -s "$SERIAL")
else
    ADB=(adb)
fi

mkdir -p "$OUT"

echo "Waiting for an authorized Android device (read-only collection only)..."
timeout 30s "${ADB[@]}" wait-for-device
state=$("${ADB[@]}" get-state)
[[ "$state" == device ]] || {
    echo "ADB state is '$state', expected 'device'" >&2
    exit 1
}

echo "--- device identity ---"
"${ADB[@]}" shell getprop ro.product.model
"${ADB[@]}" shell getprop ro.product.device
"${ADB[@]}" shell getprop ro.soc.model
"${ADB[@]}" shell getprop ro.build.fingerprint

pull_tree() {
    local source=$1
    local parent=$2
    mkdir -p "$OUT/$parent"
    echo "Pulling $source -> $OUT/$parent/"
    "${ADB[@]}" pull "$source" "$OUT/$parent/"
}

# Keep the Android hierarchy so import-firmware.py can inspect all candidates.
pull_tree /vendor/firmware vendor
pull_tree /vendor/firmware_mnt/image vendor/firmware_mnt
pull_tree /odm/etc/wifi/peach odm/etc/wifi

echo "Running checksum-only importer; incomplete inputs are left untouched."
python3 "$REF/scripts/import-firmware.py" \
    "$OUT" \
    "$REF/build/audio" \
    "$REF/sources/wireless-regdb"
