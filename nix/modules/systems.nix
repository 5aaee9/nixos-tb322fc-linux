{ inputs, self, ... }:
let
  device = import inputs.device-config;
  base = inputs.nixpkgs.lib.nixosSystem {
    system = "aarch64-linux";
    modules = [
      self.nixosModules.y700
      self.nixosModules.gnome
      ../../nixos/configuration.nix
      ({ lib, pkgs, ... }: {
        # USB/NBD maintenance images retain their established ext4 format.
        fileSystems."/".fsType = lib.mkOverride 900 "ext4";
        fileSystems."/".options = lib.mkOverride 900 [ "noatime" "errors=remount-ro" ];
        environment.systemPackages = [ pkgs.btrfs-progs ];
      })
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
