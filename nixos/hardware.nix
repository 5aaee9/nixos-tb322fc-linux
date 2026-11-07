{ lib, pkgs, ... }:

{
  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";
  assertions = [
    {
      assertion = pkgs.stdenv.hostPlatform.system == "aarch64-linux";
      message = "The Y700 TB322FC module requires an aarch64-linux host platform.";
    }
  ];

  fileSystems."/" = {
    device = lib.mkDefault "/dev/disk/by-partlabel/rootfs";
    fsType = lib.mkDefault "btrfs";
    options = lib.mkDefault [
      "noatime"
      "compress=zstd:1"
    ];
  };

  # The target kernel and Android boot image provide the actual early
  # hardware support. These values document the rootfs contract only.
  swapDevices = lib.mkDefault [ ];
}
