{ pkgs, inputs, project, boot, uefi }:
let
  arm = import inputs.nixpkgs { system = "aarch64-linux"; };
  closure = pkgs.closureInfo { rootPaths = [ arm.kexec-tools arm.dtc ]; };
  initrd = pkgs.runCommand "y700-storage-bootstrap-initrd" {
    nativeBuildInputs = [ pkgs.python3 ];
  } ''
    python ${project}/tools/build-bootstrap-initrd.py \
      --closure ${closure}/store-paths --busybox ${boot.busybox}/bin/busybox \
      --kexec ${arm.kexec-tools} --dtc ${arm.dtc} \
      --provider ${uefi.external}/u-boot.bin \
      --init ${project}/vendor/tb322fc-linux/uefi/bootstrap-init \
      --usb ${project}/vendor/tb322fc-linux/initramfs/usb-rndis \
      --firmware ${boot.firmwarePath} \
      --firmware-manifest ${project}/vendor/tb322fc-linux/firmware-tb322fc-prc.json \
      --cpio ${boot.genInitCpio}/bin/gen_init_cpio --out "$out"
    gzip -n -c "$out/initramfs.cpio" > "$out/initramfs.cpio.gz"
  '';
  mkArtifacts = { kernel ? boot.kernels.efi, initramfs ? boot.initramfs.persistent }:
    pkgs.runCommand "y700-generation-artifacts" {
      nativeBuildInputs = [ pkgs.python3 ];
    } ''
      mkdir -p "$out"
      ln -s ${kernel}/Image "$out/Image"
      ln -s ${kernel}/elden.dtb "$out/elden.dtb"
      ln -s ${initramfs}/initramfs.cpio "$out/initramfs.cpio"
      ln -s ${arm.systemd}/lib/systemd/boot/efi/systemd-bootaa64.efi "$out/systemd-bootaa64.efi"
      cp ${project}/vendor/tb322fc-linux/configs/cmdline.txt "$out/cmdline"
      python - "$out" <<'PY'
      import hashlib,json,sys
      from pathlib import Path
      out=Path(sys.argv[1])
      files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()}
      (out/"metadata.json").write_text(json.dumps({
        "schema":1,"board":"lenovo,elden","files":files,
        "kernel_provenance":json.loads(Path("${kernel}/metadata.json").read_text())
      },indent=2)+"\n")
      PY
    '';
  installer = pkgs.writeShellApplication {
    name = "y700-install-generations";
    runtimeInputs = [ pkgs.python3 pkgs.dosfstools pkgs.mtools pkgs.util-linux pkgs.coreutils ];
    text = ''
      exec python ${project}/tools/install-boot-generations.py "$@"
    '';
  };
in {
  inherit initrd mkArtifacts installer;
  artifacts = mkArtifacts {};
}
