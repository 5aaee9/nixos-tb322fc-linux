{
  description = "Pinned NixOS GNOME userspace for Lenovo Y700 Gen 4 (elden)";

  inputs.nixpkgs.url =
    "github:NixOS/nixpkgs/da6dc0e7b26060f2f71ce3ef7088fb56ee44fa36";

  outputs = { nixpkgs, ... }:
    let
      system = "aarch64-linux";
    in {
      nixosConfigurations = rec {
        elden = nixpkgs.lib.nixosSystem {
          inherit system;
          modules = [
            ./nixos/configuration.nix
            ./nixos/hardware.nix
            ./nixos/device.nix
          ];
        };
        elden-desktop = elden.extendModules {
          modules = [ ./nixos/development.nix ];
        };
      };
    };
}
