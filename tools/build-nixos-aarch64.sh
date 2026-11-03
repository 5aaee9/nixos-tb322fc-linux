#!/usr/bin/env bash
# Build the selected ARM64 NixOS closure with the Nix-provided QEMU helper.
set -euo pipefail
PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${1:-$PROJECT/result-nixos-system}
CONFIG=${2:-elden}
if [[ $# -gt 0 ]]; then shift; fi
if [[ $# -gt 0 ]]; then shift; fi
case "$CONFIG" in
    elden|elden-desktop|elden-persistent) ;;
    *) echo "Unknown NixOS configuration: $CONFIG" >&2; exit 2 ;;
esac
exec bash "$PROJECT/tools/build-artifact.sh"     "nixosConfigurations.$CONFIG.config.system.build.toplevel" "$OUT" "$@"
