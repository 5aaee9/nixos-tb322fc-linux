{ inputs, ... }:
let
  device = import inputs.device-config;
  base = inputs.nixpkgs.lib.nixosSystem {
    system = "aarch64-linux";
    modules = [
      ../../nixos/configuration.nix
      ../../nixos/hardware.nix
      ../../nixos/device.nix
    ];
  };
  desktop = base.extendModules {
    modules = [
      ../../nixos/development.nix
      { y700.debugPublicKey = device.debugPublicKey or ""; }
    ];
  };
in
{
  flake = {
    nixosModules = {
      hardware = ../../nixos/hardware.nix;
      device = ../../nixos/device.nix;
      desktop = ../../nixos/development.nix;
      persistent = ../../nixos/persistent.nix;
    };
    nixosConfigurations = {
      elden = base;
      elden-desktop = desktop;
      elden-persistent = desktop.extendModules {
        modules = [ ../../nixos/persistent.nix ];
      };
    };
  };
}
