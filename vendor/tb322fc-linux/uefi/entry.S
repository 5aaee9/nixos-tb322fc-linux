/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <linux/linkage.h>

/* Linux entry has no usable SP. Save x0 before any compiled C executes. */
.text
ENTRY(save_boot_params)
	adrp	x1, y700_incoming_fdt
	add	x1, x1, :lo12:y700_incoming_fdt
	str	x0, [x1]
	b	save_boot_params_ret
ENDPROC(save_boot_params)

.data
.balign 8
.global y700_incoming_fdt
y700_incoming_fdt:
	.quad 0
