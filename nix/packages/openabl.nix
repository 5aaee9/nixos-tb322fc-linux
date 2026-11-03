{
  pkgs,
  inputs,
  project,
}:
let
  lib = pkgs.lib;
  cross = pkgs.pkgsCross.aarch64-multiplatform.stdenv.cc;
  crossLd = cross.bintools;
  python = pkgs.python3.withPackages (p: [
    p.fonttools
    p.setuptools
    p.cryptography
  ]);
  patches = "${project}/vendor/tb322fc-linux/patches/openabl";
  mkOpenabl =
    probe:
    pkgs.stdenv.mkDerivation {
      pname = "openabl-sm8750${lib.optionalString probe "-entry-probe"}";
      version = builtins.substring 0 12 inputs.openabl-src.rev;
      src = inputs.openabl-src;
      nativeBuildInputs = [
        python
        pkgs.git
        pkgs.llvmPackages.clang
        pkgs.llvmPackages.lld
        pkgs.llvmPackages.llvm
        cross
        pkgs.perl
        pkgs.which
        pkgs.nasm
        pkgs.pkg-config
      ];
      buildInputs = [ pkgs.libuuid ];
      hardeningDisable = [ "all" ];
      dontFixup = true;
      SOURCE_DATE_EPOCH = "1793491200";
      Y700_SOURCE_INPUTS = builtins.toJSON (
        lib.genAttrs [ "nixpkgs" "openabl-src" "edk2-src" "microui-src" "qtestsign-src" ] (name: {
          inherit (inputs.${name}) rev narHash;
        })
      );
      postPatch = ''
        patch -p1 < ${patches}/0001-fix-no-standard-boot-unused-variable.patch
        mkdir -p build
        cp -R ${inputs.edk2-src} build/edk2
        chmod -R u+w build/edk2
        git -C build/edk2 apply --whitespace=nowarn "$PWD/Abl/openabl.patch"
        cp -R Abl/QcomModulePkg/. build/edk2/QcomModulePkg/
        for name in 0002-edk2-native-response-quotes.patch 0003-edk2-avb-result-enum.patch \
            0004-edk2-reject-unresolved-verity-mode.patch 0005-add-no-storage-entry-probe.patch; do
          git -C build/edk2 apply ${patches}/"$name"
        done
        cp -R ${inputs.microui-src} build/microui
        cp -R ${inputs.qtestsign-src} build/qtestsign
        patchShebangs Scripts build/edk2 build/qtestsign
        substituteInPlace build/edk2/makefile --replace-fail 'SHELL:=/bin/bash' 'SHELL:=${pkgs.bash}/bin/bash'
      '';
      configurePhase = ''
        runHook preConfigure
        make -j"$NIX_BUILD_CORES" FEATURES=park-display,sysfont \
          CC=${pkgs.llvmPackages.clang-unwrapped}/bin/clang LD=lld-link \
          PYTHON=python3 OBJ="$PWD/menu-obj" OUT="$PWD/menu"
        (
          cd build/edk2
          set +u
          . ./edksetup.sh --reconfig
          set -u
        )
        mkdir -p build/edk2/QcomModulePkg/Prebuilt/OpenAblMenu
        cp menu/openabl-menu.efi build/edk2/QcomModulePkg/Prebuilt/OpenAblMenu/
        runHook postConfigure
      '';
      buildPhase = ''
        runHook preBuild
        candidate="$PWD"
        cd build/edk2
        make all \
          "PREBUILT_HOST_TOOLS=BUILD_CC=clang BUILD_CXX=clang++ LDPATH=-fuse-ld=lld BUILD_AR=llvm-ar EXTRA_LDFLAGS=-L${lib.getLib pkgs.libuuid}/lib" \
          QSPA_BOOTCONFIG_ENABLE=0 AB_RETRYCOUNT_DISABLE=0 VERIFIED_BOOT_ENABLED=1 \
          USER_BUILD_VARIANT=1 DISABLE_PARALLEL_DOWNLOAD_FLASH=0 TARGET_ARCHITECTURE=arm64 \
          CLANG_BIN=${pkgs.llvmPackages.clang-unwrapped}/bin/ CLANG_PREFIX=${cross}/bin/${cross.targetPrefix} \
          "CLANG_EXTRA_DLINK_FLAGS=-fuse-ld=${crossLd}/bin/${cross.targetPrefix}ld.bfd -no-pie -Wl,--no-relax" \
          BOARD_BOOTLOADER_PRODUCT_NAME=OpenABL "BOARD_BOOTLOADER_PRODUCT_VERSION=$(cat "$candidate/VERSION")" \
          REMOVE_CARVEOUT_REGION=0 ABL_USB_HOST=1 OPENABL_MENU=1 \
          TB322FC_ABL_ENTRY_PROBE=${if probe then "1" else "0"} \
          PVMFW_ENABLED=true DISABLE_KERNEL_PROTOCOL=0 "BOOTLOADER_OUT=$candidate/edk2-work/obj/ABL_OBJ"
        cd "$candidate"
        python build/qtestsign/qtestsign.py -v7 -o abl-dummy-signed-sm8750.elf abl edk2-work/unsigned_abl.elf
        test "$(stat -c %s abl-dummy-signed-sm8750.elf)" -le 1048576
        runHook postBuild
      '';
      installPhase = ''
        mkdir -p "$out"
        cp abl-dummy-signed-sm8750.elf "$out/"
        cp edk2-work/unsigned_abl.elf "$out/abl-unsigned-sm8750.elf"
        cp menu/openabl-menu.efi "$out/"
        cat > "$out/NOTICE" <<'EOF'
        Offline experimental artifact only. This is not an OEM signature.
        The qtestsign v7 placeholder is not accepted by this TB322FC's firmware.
        Do not flash this output. The stock ABL remains the supported boot chain.
        EOF
        python ${project}/nix/builders/openabl-metadata.py "$PWD" ${patches} "$out" ${if probe then "1" else "0"}
        cd "$out"
        sha256sum *.elf *.efi metadata.json NOTICE > SHA256SUMS
      '';
    };
in
{
  normal = mkOpenabl false;
  entry-probe = mkOpenabl true;
}
