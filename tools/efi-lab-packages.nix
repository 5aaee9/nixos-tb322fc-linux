# Host-only ARM64 EFI interoperability lab, using the project's stable pin.
let
  lock = (builtins.fromJSON (builtins.readFile ../flake.lock)).nodes.nixpkgs.locked;
  source = builtins.fetchTree {
    type = "github";
    inherit (lock)
      owner
      repo
      rev
      narHash
      ;
  };
  host = import source { system = "x86_64-linux"; };
  arm = import source { system = "aarch64-linux"; };
in
import ../nix/packages/lab-tools.nix {
  pkgs = host;
  inherit arm;
}
