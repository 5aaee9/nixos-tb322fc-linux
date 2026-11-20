{ config, lib, pkgs, ... }:
let
  cfg = config.y700.generationBoot;
in {
  options.y700.generationBoot = {
    enable = lib.mkEnableOption "generation snapshots for the Y700 storage bootstrap";
    artifacts = lib.mkOption {
      type = lib.types.package;
      description = "Immutable board kernel, firmware stage1 and EFI loader.";
    };
    installer = lib.mkOption {
      type = lib.types.package;
      description = "Native FAT snapshot installer.";
    };
    configurationLimit = lib.mkOption {
      type = lib.types.ints.between 1 8;
      default = 3;
      description = "Number of compatible profile generations in each new snapshot.";
    };
    usbDebug = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable the development USB gadget in generated entries.";
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [{
      assertion = config.nixpkgs.hostPlatform.system == "aarch64-linux";
      message = "Y700 generation boot requires aarch64-linux.";
    }];
    boot.loader.external = {
      enable = true;
      installHook = pkgs.writeShellScript "install-y700-generations" ''
        exec ${cfg.installer}/bin/y700-install-generations \
          --limit ${toString cfg.configurationLimit} \
          ${lib.optionalString cfg.usbDebug "--usb-debug"} "$@"
      '';
    };
    boot.loader.efi.canTouchEfiVariables = false;
    system.systemBuilderCommands = ''
      ln -s ${cfg.artifacts} "$out/y700-boot"
    '';
    boot.bootspec.extensions."org.y700.board.v1" = {
      artifacts = "${cfg.artifacts}";
      selection = "exact-system-and-generation";
      media = "atomic-fat-snapshot";
    };
    environment.systemPackages = [ cfg.installer ];
  };
}
