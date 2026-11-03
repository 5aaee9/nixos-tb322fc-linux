"""Fail if Kconfig discarded a required board or transport option."""
from pathlib import Path
import sys

mode, config_path, cmdline, vendor = sys.argv[1:]
config = set(Path(config_path).read_text().splitlines())
required = {
    "CONFIG_SCSI_UFS_QCOM=y", "CONFIG_EXT4_FS=y", "CONFIG_BLK_DEV_INITRD=y",
    "CONFIG_USB_DWC3_DUAL_ROLE=y", "CONFIG_USB_GADGET=y", "CONFIG_USB_CONFIGFS_RNDIS=y",
}
required.update(line for line in (Path(vendor) / "configs/kernel-networking.config")
                .read_text().splitlines() if line.startswith("CONFIG_"))
required.add(f'CONFIG_CMDLINE="{cmdline}"')
if mode == "efi":
    required.update({"CONFIG_EFI=y", "CONFIG_EFI_STUB=y", "CONFIG_SCSI_VIRTIO=y",
                     'CONFIG_INITRAMFS_SOURCE=""'})
    for disabled in ("CONFIG_CMDLINE_FORCE=y", "CONFIG_BUILTIN_DTB=y"):
        if disabled in config:
            raise ValueError("EFI kernel must not contain " + disabled)
else:
    required.add("CONFIG_CMDLINE_FORCE=y")
required.add("CONFIG_BLK_DEV_NBD=y" if mode == "usb-nbd" else "# CONFIG_BLK_DEV_NBD is not set")
missing = required - config
if missing:
    raise ValueError("Kernel contract lost: " + ", ".join(sorted(missing)))
