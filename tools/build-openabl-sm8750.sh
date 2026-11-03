#!/usr/bin/env bash
# Offline experiment only: qtestsign does not provide OEM authentication.
set -euo pipefail
PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${1:?Usage: build-openabl-sm8750.sh NEW-OUTPUT-LINK [normal|entry-probe]}
MODE=${2:-normal}
[[ $# -le 2 ]] || { echo "Too many arguments" >&2; exit 2; }
case "$MODE" in
    normal) PACKAGE=openabl ;;
    entry-probe) PACKAGE=openabl-entry-probe ;;
    *) echo "Mode must be normal or entry-probe" >&2; exit 2 ;;
esac
exec bash "$PROJECT/tools/build-artifact.sh" "$PACKAGE" "$OUT"
