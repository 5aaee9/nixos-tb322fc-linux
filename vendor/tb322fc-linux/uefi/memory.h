/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef Y700_RAM_MEMORY_H
#define Y700_RAM_MEMORY_H
#ifdef Y700_HOST_TEST
#include <stdint.h>
#include <stddef.h>
#else
#include <linux/types.h>
#endif
#define Y700_U64_MAX (~(uint64_t)0)

#define Y700_MAX_RANGES 256
#define Y700_FDT_MAX 0x200000
struct y700_range {
	uint64_t start, size;
};
struct y700_memory {
	struct y700_range banks[Y700_MAX_RANGES];
	struct y700_range free[Y700_MAX_RANGES];
	size_t bank_count, free_count;
	struct y700_range packed, fdt, framebuffer;
	uint32_t width, height, stride;
	char format[16];
};
int y700_range_valid(struct y700_range r);
int y700_range_contains(struct y700_range a, struct y700_range b);
int y700_subtract(struct y700_range *ranges, size_t *count,
		  struct y700_range reserved);
/* Diagnostic-only scanout validation; does not authorize RAM allocation. */
int y700_probe_framebuffer(const void *fdt, uintptr_t fdt_address,
			   struct y700_range image, struct y700_memory *memory);
int y700_parse_memory(const void *fdt, uintptr_t fdt_address,
		      struct y700_range image, int lab,
		      struct y700_memory *memory);
int y700_psci_method(const void *fdt, int lab, const char **method);
#endif
