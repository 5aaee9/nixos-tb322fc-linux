#!/usr/bin/env bash
# Build through the project flake; this script never opens a device.
set -euo pipefail
PROJECT=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
exec bash "$PROJECT/tools/build-artifact.sh" boot-persistent "${ARTIFACT_DIR:-$PROJECT/result-boot-persistent}" "$@"
