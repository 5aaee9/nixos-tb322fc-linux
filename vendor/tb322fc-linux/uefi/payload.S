/* SPDX-License-Identifier: GPL-2.0-or-later */
.section .rodata.y700_ramfs, "a"
.balign 4096
.global y700_ramfs_start
y700_ramfs_start:
.incbin "board/lenovo/y700-ram/ramfs.img.gz"
.global y700_ramfs_end
y700_ramfs_end:
