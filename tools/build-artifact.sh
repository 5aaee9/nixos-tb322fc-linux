#!/usr/bin/env bash
# Compatibility entry point: all compilation and packaging is defined in Nix.
set -euo pipefail
PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
PACKAGE=${1:?Usage: build-artifact.sh PACKAGE NEW-OUTPUT-LINK [NIX-ARGS...]}
OUT=${2:?Usage: build-artifact.sh PACKAGE NEW-OUTPUT-LINK [NIX-ARGS...]}
shift 2
[[ ! -e "$OUT" && ! -L "$OUT" ]] || { echo "Output already exists: $OUT" >&2; exit 1; }
if [[ -n "${Y700_DEBUG_PUBLIC_KEY_FILE:-}" ]]; then
    echo 'Use --override-input device-config path:/PUBLIC-CONFIG --no-write-lock-file; environment key imports were removed.' >&2
    exit 1
fi
case "$PACKAGE" in
    rootfs|rootfs-base|rootfs-desktop|rootfs-archive|efi-generation|efi-esp|nixosConfigurations.*)
        exec nix run --extra-experimental-features 'nix-command flakes' "$PROJECT#build-aarch64" -- \
            "$PROJECT#$PACKAGE" --out-link "$OUT" "$@" ;;
    *) exec nix build --extra-experimental-features 'nix-command flakes' \
            "$PROJECT#$PACKAGE" --out-link "$OUT" "$@" ;;
esac
