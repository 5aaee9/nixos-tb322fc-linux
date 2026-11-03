# Host-only OpenABL build dependencies, using the existing stable input.
let
  lock = (builtins.fromJSON (builtins.readFile ../flake.lock)).nodes.nixpkgs.locked;
  source = builtins.fetchTree {
    type = "github";
    inherit (lock) owner repo rev narHash;
  };
  pkgs = import source { system = "x86_64-linux"; };
in
pkgs.linkFarm "y700-openabl-build-tools" [
  { name = "python"; path = pkgs.python3.withPackages (p: [ p.fonttools p.setuptools p.cryptography ]); }
  { name = "glibc32"; path = pkgs.pkgsi686Linux.glibc; }
  { name = "glibc32-dev"; path = pkgs.pkgsi686Linux.glibc.dev; }
]
