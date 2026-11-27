{ self, inputs, ... }:

{
  flake.nixosModules = {
    managed-kernel = { pkgs, ... }: {
      y700.useKernelPackages = true;
      boot.kernelPackages = pkgs.linuxPackagesFor (import ../packages/managed-kernel.nix {
        inherit pkgs;
        src = inputs.kernel-src;
        firmware = self.packages.${pkgs.stdenv.hostPlatform.system}.firmware;
      });
    };
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
    generation-boot = { lib, pkgs, ... }: {
      imports = [ ../../nixos/generation-boot.nix ];
      y700.generationBoot = {
        artifacts = lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.generation-boot-artifacts;
        installer = lib.mkDefault self.packages.${pkgs.stdenv.hostPlatform.system}.generation-boot-installer;
      };
    };
  };
}
