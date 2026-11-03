{ inputs, self, ... }:
{
  perSystem =
    {
      pkgs,
      system,
      self',
      ...
    }:
    let
      sourceFor =
        paths:
        pkgs.lib.fileset.toSource {
          root = ../..;
          fileset = pkgs.lib.fileset.unions (map (path: ../../. + "/${path}") paths);
        };
      deviceProject = sourceFor [
        "tools/import-nix-device-inputs.py"
        "vendor/tb322fc-linux/firmware-tb322fc-prc.json"
      ];
      device = import ../packages/device-inputs.nix {
        inherit pkgs;
        project = deviceProject;
      };
      boot = import ../packages/boot.nix {
        inherit pkgs inputs;
        inherit (device) firmware;
        project = sourceFor [
          "vendor/tb322fc-linux/configs"
          "vendor/tb322fc-linux/initramfs"
          "vendor/tb322fc-linux/patches/kernel"
          "vendor/tb322fc-linux/sources.json"
          "nix/builders/check-kernel.py"
          "nix/builders/kernel-metadata.py"
        ];
      };
      kshim = import ../packages/kshimc.nix {
        inherit pkgs inputs;
        inherit (device) stockBoot;
        project = sourceFor [
          "vendor/tb322fc-linux/patches/kshimc"
          "tools/kshimc_config.py"
          "tools/kshimc_image.py"
          "nix/builders/check-kshimc.py"
          "nix/builders/kshimc-metadata.py"
          "nix/builders/pack-kshimc.py"
          "flake.lock"
        ];
      };
      rootfs = import ../packages/rootfs.nix {
        inherit pkgs self;
        project = sourceFor [
          "tools/build-persistent-rootfs.py"
          "flake.nix"
          "flake.lock"
          "nixos/persistent.nix"
          "vendor/tb322fc-linux/sources.json"
        ];
      };
      efi = import ../packages/efi.nix {
        inherit
          pkgs
          inputs
          self
          boot
          ;
        inherit (device) firmware;
        project = sourceFor [
          "tools/build-efi-generation.py"
          "tools/build-efi-esp.py"
          "flake.lock"
          "vendor/tb322fc-linux/configs"
          "vendor/tb322fc-linux/initramfs"
          "vendor/tb322fc-linux/sources.json"
          "vendor/tb322fc-linux/firmware-tb322fc-prc.json"
        ];
      };
      openabl = import ../packages/openabl.nix {
        inherit pkgs inputs;
        project = sourceFor [
          "vendor/tb322fc-linux/patches/openabl"
          "nix/builders/openabl-metadata.py"
        ];
      };
    in
    {
      _module.args.y700 = {
        inherit
          boot
          kshim
          rootfs
          efi
          ;
      };
      legacyPackages.y700 = {
        inherit (efi) mkGeneration mkEsp;
      };
      packages = {
        default = boot.boot-persistent;
        audio-topology =
          pkgs.runCommand "y700-audio-topology"
            {
              nativeBuildInputs = [
                pkgs.m4
                pkgs.alsa-utils
              ];
            }
            ''
              mkdir -p "$out"
              m4 -I ${inputs.audioreach-src} ${../../vendor/tb322fc-linux/rootfs/audio/topology.m4} > "$out/topology.conf"
              alsatplg -c "$out/topology.conf" -o "$out/Lenovo-Y700-Gen4-tplg.bin"
              echo '33288df358504392dcc1d70ebdff4dc7a9ec8f9936edb30a65b3faa88a2000ef  '"$out/Lenovo-Y700-Gen4-tplg.bin" | sha256sum -c -
            '';
        wireless-regdb = pkgs.runCommand "y700-wireless-regdb" { } ''
          mkdir -p "$out"
          cp ${inputs.wireless-regdb-src}/regulatory.db ${inputs.wireless-regdb-src}/regulatory.db.p7s "$out/"
        '';
        firmware = device.firmware;
        busybox = boot.busybox;
        gen-init-cpio = boot.genInitCpio;
        kernel-persistent = boot.kernels.persistent;
        kernel-usb-nbd = boot.kernels.usb-nbd;
        kernel-efi = boot.kernels.efi;
        initramfs-persistent = boot.initramfs.persistent;
        initramfs-usb-nbd = boot.initramfs.usb-nbd;
        boot-persistent = boot.boot-persistent;
        boot-usb-nbd = boot.boot-usb-nbd;
        kshimc-packer = kshim.packer;
        kshimc-runtime = kshim.runtime;
        boot-kshimc = kshim.image;
        rootfs = rootfs.images.persistent;
        rootfs-base = rootfs.images.base;
        rootfs-desktop = rootfs.images.desktop;
        rootfs-archive = rootfs.archives.persistent;
        efi-generation = efi.generation;
        efi-esp = efi.esp;
        efi-lab-tools = import ../packages/lab-tools.nix {
          inherit pkgs;
          arm = import inputs.nixpkgs { system = "aarch64-linux"; };
        };
        import-device-inputs = pkgs.writeShellApplication {
          name = "import-device-inputs";
          runtimeInputs = [
            pkgs.python3
            pkgs.nix
          ];
          text = ''
            exec python ${deviceProject}/tools/import-nix-device-inputs.py \
              --generated-directory ${self'.packages.audio-topology} \
              --generated-directory ${self'.packages.wireless-regdb} "$@"
          '';
        };
        sign-boot-avb = pkgs.writeShellApplication {
          name = "sign-boot-avb";
          runtimeInputs = [
            pkgs.python3
            pkgs.openssl
          ];
          text = ''
            exec python ${../../tools/sign-boot-avb.py} --avbtool ${pkgs.android-tools}/bin/avbtool "$@"
          '';
        };
        build-aarch64 = pkgs.writeShellApplication {
          name = "build-aarch64";
          runtimeInputs = [
            pkgs.nix
            pkgs.util-linux
            pkgs.coreutils
          ];
          text = pkgs.lib.replaceStrings [ "@qemu@" ] [ "${pkgs.qemu}" ] (
            builtins.readFile ../builders/build-aarch64.sh
          );
        };
      }
      // pkgs.lib.optionalAttrs (system == "x86_64-linux") {
        openabl = openabl.normal;
        openabl-entry-probe = openabl.entry-probe;
      };
    };
}
