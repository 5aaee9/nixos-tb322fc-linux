#!/usr/bin/env bash
# Build the pinned ARM64 NixOS system with a temporary user-namespace QEMU
# handler. Nix's build sandbox remains enabled.
set -euo pipefail

PROJECT=$(cd -- "$(dirname -- "$0")/.." && pwd)
export Y700_PROJECT_ROOT="$PROJECT"
QEMU=/tmp/y700-qemu-aarch64-static
OUT_LINK="${1:-$PROJECT/result-nixos-system}"
export Y700_NIXOS_CONFIGURATION="${2:-elden}"
case "$Y700_NIXOS_CONFIGURATION" in
    elden|elden-desktop) ;;
    *) echo "Unknown NixOS configuration: $Y700_NIXOS_CONFIGURATION" >&2; exit 1 ;;
esac

command -v nix >/dev/null || {
    echo "Missing host tool: nix" >&2
    exit 1
}
command -v unshare >/dev/null || {
    echo "Missing host tool: unshare" >&2
    exit 1
}
command -v qemu-aarch64 >/dev/null || {
    echo "Missing host tool: qemu-aarch64" >&2
    exit 1
}

cp -f /usr/bin/qemu-aarch64 "$QEMU"
chmod 0755 "$QEMU"

EXPR='
let
  project = builtins.toPath (builtins.getEnv "Y700_PROJECT_ROOT");
  source = builtins.path {
    path = project;
    name = "y700-nixos-config";
    filter = path: type:
      let
        relative = builtins.substring
          (builtins.stringLength (toString project) + 1)
          (builtins.stringLength path) path;
      in
        builtins.elem relative [
          "flake.nix" "flake.lock" "nixos" "vendor"
          "vendor/tb322fc-linux" "vendor/tb322fc-linux/firmware.json"
          "vendor/tb322fc-linux/rootfs"
          "vendor/tb322fc-linux/rootfs/audio"
          "vendor/tb322fc-linux/rootfs/audio/ucm2"
        ] || builtins.match "nixos/.*" relative != null
          || builtins.match "vendor/tb322fc-linux/rootfs/audio/ucm2/.*" relative != null;
  };
  f = builtins.getFlake
    ("path:" + builtins.unsafeDiscardStringContext (toString source));
in
  (builtins.getAttr (builtins.getEnv "Y700_NIXOS_CONFIGURATION")
    f.nixosConfigurations).config.system.build.toplevel
'

cd "$PROJECT"
exec unshare -Ur -m bash -c '
    set -euo pipefail
    mount --make-rprivate / 2>/dev/null || true
    mkdir -p /tmp/binfmt-qemu
    mount -t binfmt_misc binfmt_misc /tmp/binfmt-qemu
    printf "%s\n" ":qemu-aarch64:M::\\x7f\\x45\\x4c\\x46\\x02\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\xb7\\x00:\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff:/tmp/y700-qemu-aarch64-static:OPF" > /tmp/binfmt-qemu/register
    nix --extra-experimental-features "nix-command flakes" build \
        --impure \
        --no-link \
        --print-build-logs \
        --out-link "$2" \
        --option extra-platforms aarch64-linux \
        --option build-users-group "" \
        --option require-drop-supplementary-groups false \
        --option extra-sandbox-paths /tmp/y700-qemu-aarch64-static \
        --expr "$1"
' bash "$EXPR" "$OUT_LINK"
