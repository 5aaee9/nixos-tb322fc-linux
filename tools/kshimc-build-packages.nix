# Host build dependencies from the project's pinned stable input.
let
  lock = (builtins.fromJSON (builtins.readFile ../flake.lock)).nodes.nixpkgs.locked;
  source = builtins.fetchTree {
    type = "github";
    inherit (lock) owner repo rev narHash;
  };
  pkgs = import source { system = "x86_64-linux"; };
in
pkgs.buildEnv {
  name = "y700-kshimc-build-tools";
  paths = [
    pkgs.cmake
    pkgs.ninja
    (pkgs.python3.withPackages (p: [ p.kconfiglib ]))
  ];
}
