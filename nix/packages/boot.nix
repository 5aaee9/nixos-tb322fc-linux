{
  pkgs,
  inputs,
  project,
  firmware,
}:
let
  lib = pkgs.lib;
  vendor = "${project}/vendor/tb322fc-linux";
  kernelManifest = (builtins.fromJSON (builtins.readFile "${vendor}/sources.json")).kernel;
  kernelPatches = map (patch: "${vendor}/${patch}") kernelManifest.patches;
  cross = pkgs.pkgsCross.aarch64-multiplatform;
  busybox = cross.stdenv.mkDerivation {
    pname = "y700-initramfs-busybox";
    version = "1.36.1";
    src = pkgs.fetchurl {
      url = "https://busybox.net/downloads/busybox-1.36.1.tar.bz2";
      sha256 = "b8cc24c9574d809e7279c3be349795c5d5ceb6fdf19ca709f80cde50e47de314";
    };
    nativeBuildInputs = [ pkgs.perl ];
    buildInputs = [ cross.glibc.static ];
    dontConfigure = true;
    hardeningDisable = [ "all" ];
    buildPhase = ''
      runHook preBuild
      cp ${vendor}/configs/busybox.config .config
      make ARCH=arm64 CROSS_COMPILE=${cross.stdenv.cc.targetPrefix} \
        HOSTCC=${pkgs.stdenv.cc}/bin/cc oldconfig < /dev/null
      make ARCH=arm64 CROSS_COMPILE=${cross.stdenv.cc.targetPrefix} \
        HOSTCC=${pkgs.stdenv.cc}/bin/cc -j"$NIX_BUILD_CORES" busybox
      ${cross.stdenv.cc.targetPrefix}readelf -h busybox | grep -q AArch64
      if ${cross.stdenv.cc.targetPrefix}readelf -l busybox | grep -q INTERP; then
        echo "initramfs BusyBox must be static" >&2; exit 1
      fi
      grep -qx CONFIG_NBDCLIENT=y .config
      runHook postBuild
    '';
    installPhase = ''
      mkdir -p "$out/bin"
      cp busybox "$out/bin/busybox"
      cp .config "$out/config"
    '';
  };
  genInitCpio = pkgs.runCommandCC "y700-gen-init-cpio" { } ''
    mkdir -p "$out/bin"
    $CC -O2 -o "$out/bin/gen_init_cpio" ${inputs.kernel-src}/usr/gen_init_cpio.c
  '';
  mkInitramfs =
    mode:
    pkgs.runCommand "y700-initramfs-${mode}" { } ''
      mkdir -p "$out"
      export PROJECT=${vendor} FIRMWARE_DIR=${firmware} BUSYBOX=${busybox}/bin/busybox
      cp ${vendor}/configs/${
        if mode == "usb-nbd" then "initramfs-usb-nbd.list" else "initramfs-tb322fc-prc.list"
      } initramfs.list
      chmod u+w initramfs.list
      ${lib.optionalString (mode != "usb-nbd") ''
        echo 'file /etc/usb-rndis ''${PROJECT}/initramfs/usb-rndis 0444 0 0' >> initramfs.list
      ''}
      ${lib.optionalString (mode == "readonly") ''
        echo 'file /etc/y700-root-readonly ${pkgs.writeText "y700-root-readonly" "readonly-overlay\n"} 0444 0 0' >> initramfs.list
      ''}
      ${genInitCpio}/bin/gen_init_cpio -t 0 initramfs.list > "$out/initramfs.cpio"
      cp initramfs.list "$out/"
    '';
  initramfs = {
    persistent = mkInitramfs "persistent";
    readonly = mkInitramfs "readonly";
    usb-nbd = mkInitramfs "usb-nbd";
  };
  mkKernel =
    mode:
    let
      efi = mode == "efi";
      nbd = mode == "usb-nbd";
      initrd = if efi then initramfs.persistent else initramfs.${mode};
    in
    pkgs.stdenv.mkDerivation {
      pname = "y700-kernel-${mode}";
      version = "7.2-${builtins.substring 0 12 inputs.kernel-src.rev}";
      src = inputs.kernel-src;
      patches = kernelPatches;
      nativeBuildInputs = with pkgs; [
        llvmPackages.clang-unwrapped
        llvmPackages.lld
        llvmPackages.llvm
        python3
        bison
        flex
        perl
        bc
        openssl
        pkg-config
        pahole
        git
      ];
      hardeningDisable = [ "all" ];
      dontFixup = true;
      enableParallelBuilding = true;
      KBUILD_BUILD_TIMESTAMP = "2026-11-02 00:00:00 UTC";
      KBUILD_BUILD_USER = "builder";
      KBUILD_BUILD_HOST = "nix";
      KBUILD_BUILD_VERSION = "1";
      Y700_SOURCE_INPUTS = builtins.toJSON {
        kernel = { inherit (inputs.kernel-src) rev narHash; };
        nixpkgs = { inherit (inputs.nixpkgs) rev narHash; };
      };
      prePatch = ''
        git init -q
        git -c core.autocrlf=false add -f .
        test "$(git write-tree)" = ${kernelManifest.base_tree}
      '';
      postPatch = ''
        git -c core.autocrlf=false add -f .
        test "$(git write-tree)" = ${kernelManifest.tree}
        rm -rf .git
      '';
      configurePhase = ''
        runHook preConfigure
        patchShebangs scripts
        cp ${vendor}/configs/kernel.config .config
        cmdline="$(cat ${vendor}/configs/${if nbd then "cmdline-usb-nbd.txt" else "cmdline.txt"})"
        ${lib.optionalString (!nbd) ''
          cmdline="''${cmdline/panic=0/panic=30} y700.usb-debug=1"
        ''}
        scripts/config --enable USB_DWC3_DUAL_ROLE --enable USB_GADGET \
          --enable USB_CONFIGFS_RNDIS --${if nbd then "enable" else "disable"} BLK_DEV_NBD \
          --set-str EXTRA_FIRMWARE_DIR ${firmware}
        ${
          if efi then
            ''
              cmdline=""
              scripts/config --enable EFI --enable EFI_STUB --enable EFI_ARMSTUB_DTB_LOADER \
                --disable CMDLINE_FORCE --enable CMDLINE_FROM_BOOTLOADER --set-str CMDLINE "" \
                --disable BUILTIN_DTB --set-str INITRAMFS_SOURCE "" --set-str LOCALVERSION "-y700-efi" \
                --disable EFI_VARS_PSTORE --enable SCSI_VIRTIO
            ''
          else
            ''
              scripts/config --set-str CMDLINE "$cmdline" \
                --set-str INITRAMFS_SOURCE ${initrd}/initramfs.cpio
            ''
        }
        while IFS= read -r setting; do
          [[ -z "$setting" || "$setting" == \#* ]] && continue
          [[ "$setting" =~ ^CONFIG_[A-Z0-9_]+=y$ ]]
          scripts/config --enable "''${setting%%=*}"
        done < ${vendor}/configs/kernel-networking.config
        make ARCH=arm64 LLVM=1 HOSTCC=${pkgs.stdenv.cc}/bin/cc olddefconfig
        python ${project}/nix/builders/check-kernel.py ${mode} .config "$cmdline" ${vendor}
        printf '%s\n' "$cmdline" > cmdline.txt
        runHook postConfigure
      '';
      buildPhase = ''
        runHook preBuild
        export LD_LIBRARY_PATH=${pkgs.openssl.out}/lib
        make ARCH=arm64 LLVM=1 HOSTCC=${pkgs.stdenv.cc}/bin/cc \
          HOSTLDFLAGS="-L${pkgs.openssl.out}/lib -Wl,-rpath,${pkgs.openssl.out}/lib" \
          -j"$NIX_BUILD_CORES" Image qcom/sm8750-lenovo-elden.dtb
        runHook postBuild
      '';
      installPhase = ''
        mkdir -p "$out"
        cp arch/arm64/boot/Image "$out/"
        cp arch/arm64/boot/dts/qcom/sm8750-lenovo-elden.dtb "$out/elden.dtb"
        cp .config "$out/kernel.config"
        cp include/config/kernel.release cmdline.txt "$out/"
        python ${project}/nix/builders/kernel-metadata.py "$out" ${vendor} ${mode}
      '';
      passthru = { inherit mode; };
    };
  kernels = lib.genAttrs [ "persistent" "readonly" "usb-nbd" "efi" ] mkKernel;
  mkBoot =
    mode:
    pkgs.runCommand "y700-boot-${mode}"
      {
        nativeBuildInputs = [
          pkgs.android-tools
          pkgs.python3
        ];
      }
      ''
        mkdir -p "$out"
        cp --no-preserve=mode ${kernels.${mode}}/* "$out/"
        cp ${initramfs.${mode}}/initramfs.cpio "$out/"
        touch empty-ramdisk
        mkbootimg --header_version 4 --kernel "$out/Image" --ramdisk empty-ramdisk \
          --os_version 15.0.0 --os_patch_level 2026-08 \
          --cmdline "$(cat "$out/cmdline.txt")" --output "$out/boot.img"
        python ${../builders/check-boot.py} "$out"
        cd "$out"
        sha256sum Image elden.dtb kernel.config kernel.release initramfs.cpio cmdline.txt metadata.json boot.img > SHA256SUMS
      '';
in
{
  vendorPath = vendor;
  firmwarePath = firmware;
  inherit
    busybox
    genInitCpio
    initramfs
    kernels
    ;
  boot-persistent = mkBoot "persistent";
  boot-readonly = mkBoot "readonly";
  boot-usb-nbd = mkBoot "usb-nbd";
}
