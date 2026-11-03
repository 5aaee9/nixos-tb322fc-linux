{ inputs }:
let
  lib = inputs.nixpkgs.lib;
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  names = builtins.filter (name: name != "device-config") (builtins.attrNames lock.nodes.root.inputs);
  actual = lib.genAttrs names (name: {
    rev = inputs.${name}.rev or null;
    narHash = inputs.${name}.narHash or null;
  });
  locked = name: lock.nodes.${lock.nodes.root.inputs.${name}}.locked;
  matchingLock = builtins.all (
    name:
    lib.assertMsg
      (actual.${name}.rev == (locked name).rev && actual.${name}.narHash == (locked name).narHash)
      "Y700 source ${name} differs from flake.lock; update and review the lock and source manifests together."
  ) names;
  vendor = ../../vendor/tb322fc-linux;
  kernel = builtins.fromJSON (builtins.readFile (vendor + "/sources.json"));
  shim = builtins.fromJSON (builtins.readFile (vendor + "/patches/kshimc/sources.json"));
  expected = {
    kernel-src = kernel.kernel.commit;
    audioreach-src = kernel.audioreach-topology.commit;
    wireless-regdb-src = kernel.wireless-regdb.commit;
    kshim-src = shim.runtime.revision;
    crdk-src = shim.dependencies.crdk.revision;
    picolibc-src = shim.dependencies.picolibc.revision;
    lvgl-src = shim.dependencies.lvgl.revision;
  };
  matchingManifest = builtins.all (
    name:
    lib.assertMsg (
      actual.${name}.rev == expected.${name}
    ) "Y700 source ${name} differs from its source manifest."
  ) (builtins.attrNames expected);
  matchingPatches = builtins.all (
    patch:
    lib.assertMsg (
      builtins.hashFile "sha256" (vendor + "/patches/kshimc/${patch.file}") == patch.sha256
    ) "Y700 kShimC patch ${patch.file} differs from its manifest."
  ) shim.patches;
in
{
  inherit actual;
  valid = matchingLock && matchingManifest && matchingPatches;
}
