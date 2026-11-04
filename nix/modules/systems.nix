{ inputs, self, ... }:
let
  device = import inputs.device-config;
  base = inputs.nixpkgs.lib.nixosSystem {
    system = "aarch64-linux";
    modules = [
      self.nixosModules.y700
      self.nixosModules.gnome
      ../../nixos/configuration.nix
    ];
  };
  desktop = base.extendModules {
    modules = [
      self.nixosModules.development
      ../profiles/y700-development.nix
      { y700.debugPublicKey = device.debugPublicKey or ""; }
    ];
  };
in
{
  flake = {
    nixosConfigurations = {
      elden = base;
      elden-desktop = desktop;
      elden-persistent = desktop.extendModules {
        modules = [
          ../profiles/y700-persistent.nix
        ];
      };
    };
  };
}
