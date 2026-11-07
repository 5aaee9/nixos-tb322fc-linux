"""Fail closed on the generated provider configuration and ARM64 layout."""
import json
from pathlib import Path
import struct
import sys

lab = sys.argv[1] == "lab"
config = {}
for line in Path(".config").read_text().splitlines():
    if line.startswith("CONFIG_") and "=" in line:
        key, value = line.split("=", 1)
        config[key[7:]] = value

required = ("TARGET_Y700_RAM", "EFI_LOADER", "EFI_BINARY_EXEC", "CMD_BOOTEFI_BINARY",
            "BLK", "BLKMAP", "FS_FAT", "EFI_VARIABLE_NO_STORE", "ENV_IS_NOWHERE",
            "POSITION_INDEPENDENT", "LINUX_KERNEL_IMAGE_HEADER",
            "OF_BOARD", "OF_HAS_PRIOR_STAGE", "OF_OMIT_DTB")
forbidden = ("UFS", "SCSI", "MMC", "NVME", "USB", "PCI", "MTD", "SPI_FLASH",
             "IDE", "AHCI", "SATA", "NET", "FASTBOOT", "DFU", "FAT_WRITE",
             "EFI_VARIABLE_FILE_STORE", "EFI_VARIABLE_SF_STORE",
             "EFI_RUNTIME_UPDATE_CAPSULE", "EFI_CAPSULE_ON_DISK", "CMD_SAVEENV",
             "CMD_FLASH", "CMD_NAND", "CMD_SF", "CMD_NVEDIT_EFI")
for key in required:
    if config.get(key) != "y":
        raise SystemExit(f"Required provider feature absent: CONFIG_{key}")
for key in forbidden:
    if config.get(key, "n") != "n":
        raise SystemExit(f"Prohibited provider feature: CONFIG_{key}")
if (config.get("Y700_RAM_LAB") == "y") != lab:
    raise SystemExit("Provider lab/target contract mismatch")
if config.get("BOOTCOMMAND") != '"y700boot"':
    raise SystemExit("Provider boot command changed")
if Path("u-boot.bin").exists():
    image = Path("u-boot.bin").read_bytes()
    offset, size, flags = struct.unpack_from("<QQQ", image, 8)
    if (image[56:60] != b"ARM\x64" or offset or flags != 0xA or
            not len(image) <= size <= 80 * 1024 * 1024):
        raise SystemExit("Invalid provider ARM64 image bounds/header")
    Path("provider-policy.json").write_text(json.dumps({
        "scope": "QEMU lab only" if lab else "unvalidated TB322FC RAM candidate",
        "image_bytes": len(image), "image_memory_bytes": size,
        "physical_storage_drivers": "absent",
        "persistent_variables": "disabled", "capsules": "disabled",
        "source_date_epoch": 1793664000,
    }, indent=2) + "\n")
