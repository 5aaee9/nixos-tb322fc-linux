{ ... }:

{
  flake.nixosModules = {
    default = ../../nixos/y700.nix;
    y700 = ../../nixos/y700.nix;
    gnome = ../../nixos/gnome.nix;
    # The old desktop export also included development account/USB policy.
    # Keep its name, but require consumers to opt into diagnostics separately.
    desktop = ../../nixos/gnome.nix;
    hardware = ../../nixos/hardware.nix;
    device = ../../nixos/device.nix;
    development = ../../nixos/development.nix;
    power-key = ../../nixos/power-key.nix;
    usb-nbd = ../../nixos/usb-nbd.nix;
    persistent = ../../nixos/persistent.nix;
  };
}
