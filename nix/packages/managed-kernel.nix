{ pkgs, src, firmware }:
let
  inherit (pkgs) lib;
  vendor = ../../vendor/tb322fc-linux;
  manifest = (builtins.fromJSON (builtins.readFile (vendor + "/sources.json"))).kernel;
  matches = builtins.split "CONFIG_([A-Z0-9_]+)=y" (builtins.readFile (vendor + "/configs/kernel-networking.config"));
  networking = lib.listToAttrs (map (match: lib.nameValuePair (builtins.head match) lib.kernel.yes) (lib.filter builtins.isList matches));
  boardConfig = pkgs.buildPackages.runCommand "y700-defconfig.patch" {} ''
    cp ${vendor + "/configs/kernel.config"} board.config
    chmod u+w board.config
    bash ${src}/scripts/config --file board.config --set-str INITRAMFS_SOURCE "" --set-str CMDLINE ""
    for symbol in ${lib.concatStringsSep " " (builtins.attrNames networking)}; do
      bash ${src}/scripts/config --file board.config --enable "$symbol"
    done
    diff -u --label /dev/null --label b/arch/arm64/configs/y700_defconfig /dev/null board.config > "$out" || test "$?" = 1
  '';
in pkgs.buildLinux {
  inherit src;
  version = "7.2.0";
  modDirVersion = "7.2.0-y700-nixos";
  defconfig = "y700_defconfig";
  enableCommonConfig = true;
  autoModules = true;
  kernelPatches = map (name: { inherit name; patch = vendor + "/${name}"; }) manifest.patches
    ++ [{ name = "y700-defconfig"; patch = boardConfig; }];
  structuredExtraConfig = lib.mapAttrs (_: value: lib.mkForce value) (networking // (with lib.kernel; {
    LOCALVERSION = freeform "-y700-nixos";
    BTRFS_FS = yes;
    EXT4_FS = yes;
    SCSI = yes;
    RPMB = yes;
    BLK_DEV_SD = yes;
    SCSI_UFSHCD = yes;
    SCSI_UFSHCD_PLATFORM = yes;
    SCSI_UFS_QCOM = yes;
    QCOM_PMIC_GLINK = yes;
    UCSI_PMIC_GLINK = yes;
    QCOM_Q6V5_PAS = yes;
    RPMSG_QCOM_GLINK_SMEM = yes;
    DRM_MSM = yes;
    DRM_PANEL_NOVATEK_NT36536 = yes;
    BACKLIGHT_AW99706 = yes;
    EXTRA_FIRMWARE_DIR = freeform (toString firmware);
    BUILTIN_DTB = no;
    EFI = yes;
    EFI_STUB = yes;
    EFI_ARMSTUB_DTB_LOADER = yes;
    EFI_VARS_PSTORE = no;
    USB_DWC3_DUAL_ROLE = yes;
    USB_GADGET = yes;
    USB_CONFIGFS_RNDIS = yes;
    BLK_DEV_NBD = no;
    SCSI_VIRTIO = yes;
  }));
}
