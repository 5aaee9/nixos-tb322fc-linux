#!/usr/bin/env bash
# Materialize a NixOS system closure into an ext4 image for a future
# PARTLABEL=rootfs partition. This never touches a connected device.
set -euo pipefail

PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
SYSTEM_LINK="${1:-$PROJECT/result-nixos-system}"
IMAGE="${2:-$PROJECT/artifacts/nixos-rootfs.ext4}"
SIZE="${ROOTFS_SIZE:-12G}"
SYSTEM=$(readlink -f "$SYSTEM_LINK")
STAGE="${ROOTFS_STAGE:-$PROJECT/build/nixos-rootfs}"
CLOSURE="${ROOTFS_CLOSURE:-$PROJECT/build/nixos-closure.list}"

[[ -d "$SYSTEM" ]] || {
    echo "NixOS system does not exist: $SYSTEM_LINK" >&2
    exit 1
}
[[ ! -e "$STAGE" ]] || {
    echo "Refusing to overwrite existing staging directory: $STAGE" >&2
    exit 1
}
[[ ! -e "$IMAGE" ]] || {
    echo "Refusing to overwrite existing image: $IMAGE" >&2
    exit 1
}

mkdir -p "$PROJECT/artifacts" "$PROJECT/build"
nix-store -qR "$SYSTEM" > "$CLOSURE"
mkdir -p "$STAGE/nix/store" \
    "$STAGE/dev" "$STAGE/proc" "$STAGE/sys" "$STAGE/run" \
    "$STAGE/tmp" "$STAGE/var" "$STAGE/home" "$STAGE/root" \
    "$STAGE/etc" "$STAGE/usr" "$STAGE/bin" "$STAGE/sbin" \
    "$STAGE/lib" "$STAGE/lib64" "$STAGE/mnt"

while IFS= read -r path; do
    cp -a --no-preserve=ownership "$path" "$STAGE/nix/store/"
done < "$CLOSURE"

ln -s "/nix/store/$(basename "$SYSTEM")/init" "$STAGE/init"
ln -s "/nix/store/$(basename "$SYSTEM")/init" "$STAGE/sbin/init"
chmod 1777 "$STAGE/tmp"

# The target filesystem must start with root-owned system files. Keep the
# staging tree private to this build and preserve the source store untouched.
sudo chown -R root:root "$STAGE"

truncate -s "$SIZE" "$IMAGE"
mke2fs -q -F -t ext4 -L rootfs -d "$STAGE" "$IMAGE"
sha256sum "$IMAGE" | tee "$IMAGE.sha256"
du -h "$IMAGE" "$IMAGE.sha256"
