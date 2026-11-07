"""Install the local RAM board overlay into the pinned U-Boot source."""
from pathlib import Path
import shutil
import sys

overlay, media = map(Path, sys.argv[1:3])
board = Path("board/lenovo/y700-ram")
board.mkdir(parents=True)
for name in ("Kconfig", "Makefile", "board.c", "memory.c", "memory.h", "payload.S", "entry.S"):
    shutil.copyfile(overlay / name, board / name)
shutil.copyfile(overlay.parent / "diagnostics/boot-stage.h", board / "boot-stage.h")
shutil.copyfile(overlay / "board.h", "include/configs/y700-ram.h")
shutil.copyfile(overlay / "defconfig", "configs/y700_ram_defconfig")
shutil.copyfile(media / "ramfs.img.gz", board / "ramfs.img.gz")
(board / "payload-size.h").write_text(
    f"#define Y700_RAMFS_SIZE { (media / 'ramfs.img').stat().st_size }UL\n")
kconfig = Path("arch/arm/Kconfig")
text = kconfig.read_text()
anchor = "config ARCH_SNAPDRAGON\n"
assert text.count(anchor) == 1
text = text.replace(anchor, """config TARGET_Y700_RAM
\tbool "TB322FC isolated RAM UEFI provider"
\tselect ARM64
\tselect DM
\tselect DM_SERIAL
\tselect BLK
\tselect OF_CONTROL
\tselect OF_BOARD
\tselect OF_HAS_PRIOR_STAGE
\tselect LINUX_KERNEL_IMAGE_HEADER
\tselect BOARD_LATE_INIT
\tselect SYSRESET
\tselect SYSRESET_PSCI
\tselect MMU_PGPROT

""" + anchor)
text += '\nsource "board/lenovo/y700-ram/Kconfig"\n'
kconfig.write_text(text)
