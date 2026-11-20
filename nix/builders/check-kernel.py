"""Fail if Kconfig discarded a required board or transport option."""
from pathlib import Path
import sys

mode, config_path, cmdline, vendor = sys.argv[1:]
config = set(Path(config_path).read_text().splitlines())
required = {
    "CONFIG_SCSI_UFS_QCOM=y", "CONFIG_EXT4_FS=y", "CONFIG_BLK_DEV_INITRD=y",
    "CONFIG_USB_DWC3_DUAL_ROLE=y", "CONFIG_USB_GADGET=y", "CONFIG_USB_CONFIGFS_RNDIS=y",
    "CONFIG_QCOM_PMIC_GLINK=y", "CONFIG_UCSI_PMIC_GLINK=y",
    "CONFIG_QCOM_Q6V5_PAS=y", "CONFIG_RPMSG_QCOM_GLINK_SMEM=y",
}
required.update(line for line in (Path(vendor) / "configs/kernel-networking.config")
                .read_text().splitlines() if line.startswith("CONFIG_"))
required.add(f'CONFIG_CMDLINE="{cmdline}"')
if mode in ("efi", "bootstrap"):
    required.update({"CONFIG_EFI=y", "CONFIG_EFI_STUB=y", "CONFIG_SCSI_VIRTIO=y",
                     'CONFIG_INITRAMFS_SOURCE=""'})
    for disabled in ("CONFIG_CMDLINE_FORCE=y", "CONFIG_BUILTIN_DTB=y"):
        if disabled in config:
            raise ValueError("EFI kernel must not contain " + disabled)
    if mode == "bootstrap":
        required.update({"CONFIG_KEXEC=y", "CONFIG_BTRFS_FS=y", "CONFIG_DRM_SIMPLEDRM=y",
                         "CONFIG_DRM_FBDEV_EMULATION=y"})
        for name in ("DRM_MSM", "DRM_PANEL_NOVATEK_NT36536", "BACKLIGHT_AW99706", "WLAN", "BT"):
            if f"CONFIG_{name}=y" in config or f"CONFIG_{name}=m" in config:
                raise ValueError("Bootstrap must not initialize " + name)
else:
    required.update({"CONFIG_CMDLINE_FORCE=y", "CONFIG_BUILTIN_DTB=y",
                     'CONFIG_BUILTIN_DTB_NAME="qcom/sm8750-lenovo-elden"'})
if mode == "readonly":
    required.update({"CONFIG_OVERLAY_FS=y", "CONFIG_TMPFS=y", "CONFIG_TMPFS_XATTR=y"})
required.add("CONFIG_BLK_DEV_NBD=y" if mode == "usb-nbd" else "# CONFIG_BLK_DEV_NBD is not set")
missing = required - config
if missing:
    raise ValueError("Kernel contract lost: " + ", ".join(sorted(missing)))
