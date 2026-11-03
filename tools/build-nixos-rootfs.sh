#!/usr/bin/env bash
# Build the registered ARM64 rootfs as a Nix artifact, without sudo/staging.
set -euo pipefail
PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
PROFILE=${1:-persistent}
OUT=${2:-$PROJECT/result-rootfs}
if [[ $# -gt 0 ]]; then shift; fi
if [[ $# -gt 0 ]]; then shift; fi
case "$PROFILE" in
    persistent) PACKAGE=rootfs ;;
    desktop) PACKAGE=rootfs-desktop ;;
    base) PACKAGE=rootfs-base ;;
    *) echo "Usage: $0 {persistent|desktop|base} [NEW-OUTPUT-LINK] [NIX-ARGS...]" >&2; exit 2 ;;
esac
exec bash "$PROJECT/tools/build-artifact.sh" "$PACKAGE" "$OUT" "$@"
