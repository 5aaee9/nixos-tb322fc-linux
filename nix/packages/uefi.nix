{ pkgs, inputs, project, boot }:
let
  lib = pkgs.lib;
  overlay = "${project}/vendor/tb322fc-linux/uefi";
  pin = builtins.fromJSON (builtins.readFile (overlay + "/source.json"));
  arm = import inputs.nixpkgs { system = "aarch64-linux"; };
  cross = pkgs.pkgsCross.aarch64-multiplatform;
  source = pkgs.fetchurl {
    inherit (pin) url hash;
    name = "u-boot-${pin.revision}.tar.gz";
  };
  mkLabMedia = entry: pkgs.runCommand "y700-uefi-lab-media-${entry}" {
    nativeBuildInputs = [ pkgs.python3 pkgs.dosfstools pkgs.mtools pkgs.libfaketime ];
  } ''
    python ${project}/tools/build-uefi-ramfs.py --out "$out" \
      --loader ${arm.systemd}/lib/systemd/boot/efi/systemd-bootaa64.efi \
      --kernel ${arm.linuxPackages.kernel}/Image \
      --busybox ${boot.busybox}/bin/busybox \
      --gen-init-cpio ${boot.genInitCpio}/bin/gen_init_cpio --default ${entry}
  '';
  diagnosticInitrd = pkgs.runCommand "y700-uefi-diagnostic-initrd" {
    nativeBuildInputs = [ pkgs.python3 ];
  } ''
    mkdir -p "$out"
    python - ${boot.initramfs.persistent}/initramfs.list initramfs.list <<'PY'
    from pathlib import Path
    import sys
    text = Path(sys.argv[1]).read_text()
    lines = text.splitlines()
    found = [i for i, line in enumerate(lines) if line.startswith("file /init ")]
    assert len(found) == 1
    lines[found[0]] = "file /init ${overlay}/diagnostic-init 0755 0 0"
    Path(sys.argv[2]).write_text("\n".join(lines) + "\n")
    PY
    # The retained list names the exact private firmware input through its
    # original expansion variables; no mutable host path is consulted.
    export PROJECT=${boot.vendorPath} FIRMWARE_DIR=${boot.firmwarePath} BUSYBOX=${boot.busybox}/bin/busybox
    ${boot.genInitCpio}/bin/gen_init_cpio -t 0 initramfs.list > "$out/initramfs.cpio"
    cp initramfs.list "$out/"
  '';
  targetMedia = pkgs.runCommand "y700-uefi-target-media" {
    nativeBuildInputs = [ pkgs.python3 pkgs.dosfstools pkgs.mtools pkgs.libfaketime ];
  } ''
    python ${project}/tools/build-uefi-ramfs.py --out "$out" \
      --loader ${arm.systemd}/lib/systemd/boot/efi/systemd-bootaa64.efi \
      --kernel ${boot.kernels.efi}/Image \
      --target-initrd ${diagnosticInitrd}/initramfs.cpio \
      --cmdline ${boot.vendorPath}/configs/cmdline.txt
  '';
  targetDtb = pkgs.runCommand "y700-uefi-target-dtb" {
    nativeBuildInputs = [ pkgs.python3 pkgs.dtc ];
  } ''
    mkdir -p "$out"
    python ${project}/nix/builders/prepare-uefi-dtb.py ${boot.kernels.efi}/elden.dtb "$out/elden.dtb"
  '';
  mkNixosMediaWith = { generation, persistent ? false }: pkgs.runCommand "y700-uefi-nixos-${if persistent then "persistent" else "readonly"}-media" {
    nativeBuildInputs = [ pkgs.python3 pkgs.dosfstools pkgs.mtools pkgs.libfaketime ];
  } ''
    python ${project}/tools/build-uefi-ramfs.py --out "$out" \
      --loader ${arm.systemd}/lib/systemd/boot/efi/systemd-bootaa64.efi \
      --kernel ${generation}/linux.efi --generation ${generation} \
      ${lib.optionalString persistent "--persistent-root"}
  '';
  mkNixosMedia = generation: mkNixosMediaWith { inherit generation; };
  mkProvider = { media, lab ? false }:
    cross.buildUBoot {
      version = builtins.substring 0 12 pin.revision;
      src = source;
      defconfig = "y700_ram_defconfig";
      pname = "y700-ram-uefi${lib.optionalString lab "-qemu-lab"}";
      filesToInstall = [ "u-boot.bin" "u-boot" ".config" "u-boot.map" ];
      SOURCE_DATE_EPOCH = "1793664000";
      extraConfig = lib.optionalString lab "CONFIG_Y700_RAM_LAB=y\n";
      postPatch = ''
        python ${project}/nix/builders/prepare-uefi.py ${overlay} ${media}
        patchShebangs tools scripts
      '';
      postConfigure = ''
        make olddefconfig
        python ${project}/nix/builders/check-uefi.py ${if lab then "lab" else "target"}
      '';
      postBuild = ''
        python ${project}/nix/builders/check-uefi.py ${if lab then "lab" else "target"}
      '';
      postInstall = ''
        cp ${overlay}/source.json "$out/source.json"
        cp ${media}/metadata.json "$out/media.json"
        cp provider-policy.json "$out/"
        ${lib.optionalString lab ''echo 'QEMU lab only; never send this image to a tablet.' > "$out/NOTICE"''}
        cd "$out"
        sha256sum u-boot.bin u-boot .config u-boot.map source.json media.json provider-policy.json > SHA256SUMS
      '';
    };
  mediaA = mkLabMedia "a";
  mediaB = mkLabMedia "b";
  memoryCheck = pkgs.runCommandCC "y700-uefi-memory-check" {
    nativeBuildInputs = [ pkgs.dtc ];
  } ''
    $CC -std=c11 -Wall -Wextra -Werror -Wno-sign-compare \
      -fsanitize=address,undefined -DY700_HOST_TEST \
      -I${overlay} -I${pkgs.dtc}/include \
      ${overlay}/memory.c ${project}/tests/uefi_memory_test.c \
      -L${pkgs.dtc}/lib -lfdt -o memory-test
    ASAN_OPTIONS=detect_leaks=0 ./memory-test
    $CC -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
      -I${project}/vendor/tb322fc-linux/diagnostics \
      ${project}/tests/boot_stage_test.c -o boot-stage-test
    ASAN_OPTIONS=detect_leaks=0 ./boot-stage-test
    mkdir -p "$out"
    cp memory-test boot-stage-test "$out/"
  '';
in {
  inherit mkProvider mkNixosMedia mkNixosMediaWith mediaA mediaB source memoryCheck targetDtb targetMedia diagnosticInitrd;
  target = mkProvider { media = targetMedia; };
  labA = mkProvider { media = mediaA; lab = true; };
  labB = mkProvider { media = mediaB; lab = true; };
}
