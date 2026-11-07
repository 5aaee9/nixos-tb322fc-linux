/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <libfdt.h>
#include <stdio.h>
#include <string.h>
#include "memory.h"

static unsigned char fdt[16384] __attribute__((aligned(8)));
static struct y700_memory map;

static void make_tree(int lab)
{
	int n, chosen;
	fdt64_t reg[] = {cpu_to_fdt64(0x40000000), cpu_to_fdt64(0x80000000)};
	assert(!fdt_create_empty_tree(fdt, sizeof(fdt)));
	assert(!fdt_setprop_u32(fdt, 0, "#address-cells", 2));
	assert(!fdt_setprop_u32(fdt, 0, "#size-cells", 2));
	assert(!fdt_setprop_string(fdt, 0, "compatible",
				  lab ? "linux,dummy-virt" : "lenovo,elden"));
	n = fdt_add_subnode(fdt, 0, "memory@40000000");
	assert(n >= 0);
	assert(!fdt_setprop_string(fdt, n, "device_type", "memory"));
	assert(!fdt_setprop(fdt, n, "reg", reg, sizeof(reg)));
	chosen = fdt_add_subnode(fdt, 0, "chosen");
	assert(chosen >= 0);
	if (!lab) {
		fdt64_t packed[] = {cpu_to_fdt64(0x42000000), cpu_to_fdt64(0x4000000)};
		fdt64_t fb[] = {cpu_to_fdt64(0x80000000), cpu_to_fdt64(0x2000000)};
		assert(!fdt_setprop(fdt, chosen, "y700,uefi-packed-range",
				   packed, sizeof(packed)));
		n = fdt_add_subnode(fdt, 0, "framebuffer");
		assert(n >= 0);
		assert(!fdt_setprop_string(fdt, n, "compatible", "simple-framebuffer"));
		assert(!fdt_setprop(fdt, n, "reg", fb, sizeof(fb)));
		assert(!fdt_setprop_u32(fdt, n, "width", 1904));
		assert(!fdt_setprop_u32(fdt, n, "height", 3040));
		assert(!fdt_setprop_u32(fdt, n, "stride", 7616));
		assert(!fdt_setprop_string(fdt, n, "format", "a8r8g8b8"));
	}
}

static int parse(int lab)
{
	return y700_parse_memory(fdt, 0x41000000,
				 (struct y700_range){0x43000000, 0x1000000},
				 lab, &map);
}

static int free_contains(uint64_t p)
{
	size_t i;
	for (i = 0; i < map.free_count; i++)
		if (y700_range_contains(map.free[i], (struct y700_range){p, 1}))
			return 1;
	return 0;
}

static void test_psci(void)
{
	const char *method;
	const char *versions[] = {"arm,psci-0.2", "arm,psci-1.0"};
	for (size_t i = 0; i < sizeof(versions) / sizeof(versions[0]); ++i) {
		make_tree(0);
		int n = fdt_add_subnode(fdt, 0, "psci");
		assert(n >= 0);
		assert(!fdt_setprop_string(fdt, n, "compatible", versions[i]));
		assert(!fdt_setprop_string(fdt, n, "method", "smc"));
		assert(!y700_psci_method(fdt, 0, &method));
		assert(!strcmp(method, "smc"));
		assert(y700_psci_method(fdt, 1, &method) == -8 && !method);
		assert(!fdt_setprop_string(fdt, n, "method", "hvc"));
		assert(!y700_psci_method(fdt, 1, &method));
		assert(!strcmp(method, "hvc"));
		assert(y700_psci_method(fdt, 0, &method) == -8 && !method);
		assert(!fdt_setprop(fdt, n, "method", "smc", 3));
		assert(y700_psci_method(fdt, 0, &method) == -8 && !method);
		assert(!fdt_setprop(fdt, n, "method", "smcx", 4));
		assert(y700_psci_method(fdt, 0, &method) == -8 && !method);
		assert(!fdt_delprop(fdt, n, "method"));
		assert(y700_psci_method(fdt, 0, &method) == -8 && !method);
		assert(!fdt_setprop_string(fdt, n, "method", "smc"));
		assert(!fdt_setprop_string(fdt, n, "compatible", "arm,psci"));
		assert(y700_psci_method(fdt, 0, &method) == -8 && !method);
	}
	make_tree(0);
	assert(y700_psci_method(fdt, 0, &method) == -8 && !method);
	assert(y700_psci_method(fdt, 0, NULL) == -8);
}

int main(void)
{
	struct y700_range r[256] = {{0x1000, 0x5000}};
	size_t count = 1;
	int n;
	test_psci();
	assert(!y700_subtract(r, &count, (struct y700_range){0x2800, 1}));
	assert(count == 2 && r[0].start == 0x1000 && r[0].size == 0x1000 &&
	       r[1].start == 0x3000 && r[1].size == 0x3000);
	assert(y700_subtract(r, &count, (struct y700_range){UINT64_MAX - 3, 8}));
	assert(y700_subtract(r, &count, (struct y700_range){0, 0}));
	make_tree(1);
	assert(!parse(1));
	assert(!free_contains(0x43000000) && !free_contains(0x41000000));
	assert(free_contains(0x80000000));
	assert(parse(0) == -2);
	make_tree(0);
	assert(!y700_probe_framebuffer(fdt, 0x41000000,
				       (struct y700_range){0x43000000, 0x1000000},
				       &map));
	assert(map.framebuffer.start == 0x80000000);
	assert(!parse(0));
	assert(y700_parse_memory(fdt, 0x80001000,
				(struct y700_range){0x43000000, 0x1000000},
				0, &map) == -6);
	assert(y700_parse_memory(fdt, 0x43001000,
				(struct y700_range){0x43000000, 0x1000000},
				0, &map) == -4);
	assert(!y700_parse_memory(fdt, 0x42001000,
				 (struct y700_range){0x43000000, 0x1000000},
				 0, &map));
	assert(!parse(0));
	assert(!free_contains(0x80000000) && !free_contains(0x42000000));
	assert(free_contains(0x82000000));
	assert(parse(1) == -2);
	assert(!fdt_add_mem_rsv(fdt, 0x50000000, 0x2000));
	assert(!parse(0));
	assert(!free_contains(0x50000000) && free_contains(0x50002000));
	assert(!fdt_add_mem_rsv(fdt, 0x43001000, 0x1000));
	assert(parse(0) == -7);
	make_tree(0);
	n = fdt_path_offset(fdt, "/chosen");
	assert(!fdt_delprop(fdt, n, "y700,uefi-packed-range"));
	assert(parse(0) == -4);
	make_tree(0);
	n = fdt_path_offset(fdt, "/framebuffer");
	assert(!fdt_setprop_u32(fdt, n, "stride", 7615));
	assert(parse(0) == -6);
	assert(y700_probe_framebuffer(fdt, 0x41000000,
				      (struct y700_range){0x43000000, 0x1000000},
				      &map));
	make_tree(0);
	n = fdt_add_subnode(fdt, 0, "reserved-memory");
	assert(n >= 0);
	assert(!fdt_setprop_u32(fdt, n, "#address-cells", 2));
	assert(!fdt_setprop_u32(fdt, n, "#size-cells", 2));
	n = fdt_add_subnode(fdt, n, "unresolved-dynamic-region");
	assert(n >= 0);
	assert(!fdt_setprop_u32(fdt, n, "size", 0x1000));
	assert(parse(0) == -5);
	/* A reservation refusal must remain visible without weakening allocation. */
	assert(!y700_probe_framebuffer(fdt, 0x41000000,
				       (struct y700_range){0x43000000, 0x1000000},
				       &map));
	assert(parse(0) == -5);
	assert(!fdt_setprop_string(fdt, n, "status", "disabled"));
	assert(!parse(0));
	fdt64_t disabled_reg[] = {cpu_to_fdt64(0x43000000), cpu_to_fdt64(0x1000)};
	assert(!fdt_setprop(fdt, n, "reg", disabled_reg, sizeof(disabled_reg)));
	assert(parse(0) == -7); /* A disabled device does not release firmware RAM. */
	make_tree(1);
	n = fdt_path_offset(fdt, "/memory@40000000");
	assert(!fdt_setprop_u32(fdt, n, "reg", 0));
	assert(parse(1) == -3);
	make_tree(1);
	((struct fdt_header *)fdt)->totalsize = cpu_to_fdt32(Y700_FDT_MAX + 8);
	assert(parse(1) == -1);
	puts("UEFI actual memory parser: positive target/lab and refusal cases passed");
	return 0;
}
