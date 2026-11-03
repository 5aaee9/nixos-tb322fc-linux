#!/usr/bin/env bash
# The historical direct image is now the persistent-root Nix profile.
set -euo pipefail
PROJECT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
MODE=${1:-all}
if [[ $# -gt 0 ]]; then shift; fi
case "$MODE" in
    all) PACKAGE=boot-persistent ;;
    initramfs) PACKAGE=initramfs-persistent ;;
    *) echo "Usage: $0 [all|initramfs] [NIX-ARGS...]" >&2; exit 2 ;;
esac
exec bash "$PROJECT/tools/build-artifact.sh" "$PACKAGE" "${ARTIFACT_DIR:-$PROJECT/result-$PACKAGE}" "$@"
