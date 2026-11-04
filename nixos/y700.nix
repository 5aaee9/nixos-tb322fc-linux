{ lib, ... }:

{
  imports = [
    ./hardware.nix
    ./device.nix
    ./persistent.nix
    ./usb-nbd.nix
    ./power-key.nix
  ];

  # The separately built Android boot image supplies the kernel and stage 1.
  boot.initrd.enable = lib.mkDefault false;
  boot.loader.grub.enable = lib.mkDefault false;
  boot.loader.systemd-boot.enable = lib.mkDefault false;

  networking.networkmanager.enable = lib.mkDefault true;
}
