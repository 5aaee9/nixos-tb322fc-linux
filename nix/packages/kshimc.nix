{
  pkgs,
  inputs,
  project,
  stockBoot,
  linuxKernel,
  uefiProvider,
  uefiDtb,
}:
let
  patches = "${project}/vendor/tb322fc-linux/patches/kshimc";
  python = pkgs.python3.withPackages (p: [ p.kconfiglib ]);
  cross = pkgs.pkgsCross.aarch64-multiplatform.stdenv.cc;
  source =
    pkgs.runCommand "y700-kshimc-source"
      {
        nativeBuildInputs = [
          pkgs.git
          pkgs.python3
        ];
      }
      ''
        cp -R ${inputs.kshim-src} "$out"
        chmod -R u+w "$out"
        cd "$out"
        python - ${patches} <<'PY'
        import hashlib,json,subprocess,sys
        from pathlib import Path
        directory=Path(sys.argv[1])
        manifest=json.loads((directory/"sources.json").read_text())
        for item in manifest["patches"]:
            assert hashlib.sha256((directory/item["file"]).read_bytes()).hexdigest()==item["sha256"]
        for item in manifest["patches"]:
            subprocess.run(["git", "apply", str(directory/item["file"])], check=True)
        PY
        cp ${project}/vendor/tb322fc-linux/diagnostics/boot-stage.h vendor/kshim/src/include/y700_boot_stage.h
        cp -R ${inputs.picolibc-src} vendor/kshim/lib/picolibc
        mkdir -p vendor/kshim/third_party
        cp -R ${inputs.lvgl-src} vendor/kshim/third_party/lvgl
      '';
  crdkArchive = pkgs.runCommand "kshimc-crdk-source.tar" { } ''
    tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
      -C ${inputs.crdk-src} -cf "$out" .
  '';
  environment = ''
    export SOURCE_DATE_EPOCH=1793213118
    export KSHIM_CRDK_SOURCE_ARCHIVE=${crdkArchive}
    export KSHIM_CRDK_ARCHIVE_SHA256="$(sha256sum ${crdkArchive} | cut -d' ' -f1)"
    export KSHIM_CRDK_REVISION=${inputs.crdk-src.rev}
  '';
  packer = pkgs.stdenv.mkDerivation {
    pname = "kshimc-packer";
    version = builtins.substring 0 12 inputs.kshim-src.rev;
    src = inputs.kshim-src;
    nativeBuildInputs = [
      pkgs.cmake
      pkgs.ninja
      pkgs.python3
    ];
    postPatch = ''
      substituteInPlace vendor/packer/CMakeLists.txt --replace-fail \
        'set(CMAKE_EXE_LINKER_FLAGS "''${CMAKE_EXE_LINKER_FLAGS} -static")' \
        '# Nix provides the runtime linker and libc through the closure.'
    '';
    cmakeDir = "../vendor/packer";
    cmakeFlags = [ "-DBUILD_SHIMS=OFF" ];
    installPhase = ''
      mkdir -p "$out/bin"
      cp MultiBootKernelPatcher UnpackTool "$out/bin/"
    '';
  };
  menuCheck =
    pkgs.runCommandCC "kshimc-menu-check"
      {
        nativeBuildInputs = [
          pkgs.cmake
          pkgs.ninja
          python
          pkgs.git
          pkgs.dtc
        ];
      }
      ''
        ${environment}
        cmake -S ${source}/vendor/kshim/tests -B build -G Ninja -DKSHIM_TEST_SANITIZERS=ON
        cmake --build build --target tb322fc_diagnostic_test mmu_test linux_inplace_test -j"$NIX_BUILD_CORES"
        ASAN_OPTIONS=detect_leaks=0 ./build/tb322fc_diagnostic_test
        ASAN_OPTIONS=detect_leaks=0 ./build/mmu_test
        ASAN_OPTIONS=detect_leaks=0 ./build/linux_inplace_test
        mkdir -p "$out"
        cp build/tb322fc_diagnostic_test build/mmu_test build/linux_inplace_test "$out/"
      '';
  runtime =
    pkgs.runCommand "kshimc-tb322fc-runtime"
      {
        nativeBuildInputs = [
          pkgs.cmake
          pkgs.ninja
          python
          pkgs.git
          cross
        ];
        hardeningDisable = [ "all" ];
        Y700_SOURCE_INPUTS = builtins.toJSON (
          pkgs.lib.genAttrs [ "nixpkgs" "kshim-src" "crdk-src" "picolibc-src" "lvgl-src" ] (name: {
            inherit (inputs.${name}) rev narHash;
          })
        );
      }
      ''
        ${environment}
        export KSHIM_TOOLCHAIN_PREFIX=${cross}/bin/${cross.targetPrefix}
        mkdir build
        cp ${patches}/tb322fc_diagnostic_defconfig build/.config
        cmake -S ${source}/vendor/kshim -B build -G Ninja \
          -DKSHIM_STANDALONE=OFF -DKSHIM_RUNTIME_SLOT_SIZE=0x400000 \
          -DKSHIM_UEFI_PAYLOAD= -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
        python ${project}/nix/builders/check-kshimc.py build
        cmake --build build -j"$NIX_BUILD_CORES"
        python ${project}/nix/builders/check-kshimc.py build
        test -z "$(${cross.targetPrefix}nm -u build/kShimC.elf)"
        mkdir -p "$out"
        cp build/kShimC.bin build/kShimC.elf build/.config build/compile_commands.json "$out/"
        cp build/CMakeCache.txt "$out/"
        cp build/generated/include/config.h "$out/"
        python ${project}/nix/builders/kshimc-metadata.py build "$out" ${patches} ${project}/flake.lock
      '';
  image =
    pkgs.runCommand "boot-kshimc-tb322fc-diag"
      {
        nativeBuildInputs = [
          python
          packer
        ];
        preferLocalBuild = true;
        allowSubstitutes = false;
      }
      ''
        test -x ${menuCheck}/tb322fc_diagnostic_test
        python ${project}/nix/builders/pack-kshimc.py ${stockBoot} ${runtime} "$out"
      '';
  imageLinux =
    pkgs.runCommand "boot-kshimc-tb322fc-linux-ram"
      {
        nativeBuildInputs = [ python packer ];
        preferLocalBuild = true;
        allowSubstitutes = false;
      }
      ''
        test -x ${menuCheck}/tb322fc_diagnostic_test
        python ${project}/nix/builders/pack-kshimc.py ${stockBoot} ${runtime} "$out" \
          --linux ${linuxKernel}
      '';
  mkUefiImage = { provider ? uefiProvider, dtb ? uefiDtb, installable ? false }:
    pkgs.runCommand "boot-kshimc-tb322fc-uefi-${if installable then "installed" else "ram"}"
      {
        nativeBuildInputs = [ python packer ];
        preferLocalBuild = true;
        allowSubstitutes = false;
      }
      ''
        test -x ${menuCheck}/linux_inplace_test
        python ${project}/nix/builders/pack-kshimc.py ${stockBoot} ${runtime} "$out" \
          --uefi ${provider} --uefi-dtb ${dtb} \
          ${pkgs.lib.optionalString installable "--installable"}
      '';
  imageUefi = mkUefiImage { };
in
{
  inherit
    source
    packer
    menuCheck
    runtime
    image
    imageLinux
    imageUefi
    mkUefiImage
    ;
}
