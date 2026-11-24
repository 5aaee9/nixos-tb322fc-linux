{ config, lib, options, pkgs, ... }:
let
  kernel = pkgs.requireFile {
    name = "y700-efi-Image";
    sha256 = "a9717aec56fe40e1308227914a5e085788ec8d6b6318bf1e52810526c27d2f3e";
    message = "Import the verified Y700 EFI kernel with nix-store --add-fixed sha256.";
  };
  stage1 = pkgs.requireFile {
    name = "y700-persistent.cpio";
    sha256 = "fb4dfee6f934326b4c1af15d66452170b970ff33440626dd1b84fdf7bd818cfc";
    message = "Import the verified device-specific Y700 stage1 with nix-store --add-fixed sha256.";
  };
  nativeInit = pkgs.runCommand "y700-bootspec-init" {} ''
    cp ${../vendor/tb322fc-linux/initramfs/init} init
    ${pkgs.buildPackages.patch}/bin/patch --fuzz=0 init < ${./native-init.patch}
    install -m755 init "$out"
  '';
  boardParams = lib.filter (arg: !(lib.hasPrefix "init=" arg || lib.hasPrefix "panic=" arg || arg == "efi=noruntime"))
    (lib.splitString " " (lib.removeSuffix "\n" (builtins.readFile ../vendor/tb322fc-linux/configs/cmdline.txt)));
in lib.mkIf config.boot.loader.systemd-boot.enable {
  boot.loader.systemd-boot = { configurationLimit = lib.mkDefault 1; editor = lib.mkDefault false; };
  boot.loader.efi.canTouchEfiVariables = false;
  boot.bootspec.writer = options.boot.bootspec.writer.default + "\n" + ''
    (
      set -euo pipefail
      mkdir -p native-stage1/etc
      cd native-stage1
      cp ${nativeInit} init
      chmod 755 init
      printf '%s\n' "$out" > etc/y700-efi-system
      touch -d @1 init etc/y700-efi-system
      { cat ${stage1}; printf '%s\n' init etc/y700-efi-system | ${pkgs.buildPackages.cpio}/bin/cpio --quiet --reproducible --owner=0:0 -o -H newc; } | ${pkgs.buildPackages.gzip}/bin/gzip -n > "$out/y700-initrd.gz"
      ${pkgs.buildPackages.jq}/bin/jq --arg kernel '${kernel}' --arg initrd "$out/y700-initrd.gz" --argjson params '${builtins.toJSON (boardParams ++ [ "panic=30" ] ++ lib.optional (builtins.elem "y700.usb-debug=1" config.boot.kernelParams) "y700.usb-debug=1")}' \
        '."org.nixos.bootspec.v1" |= (.kernel=$kernel | .initrd=$initrd | .kernelParams=$params)' "$out/boot.json" > boot.json
      mv boot.json "$out/boot.json"
    )
  '';
}
