/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "memory.h"
#ifdef Y700_HOST_TEST
#include <libfdt.h>
#include <string.h>
#else
#include <linux/libfdt.h>
#include <linux/string.h>
#endif

int y700_range_valid(struct y700_range r)
{
	return r.size && r.start <= Y700_U64_MAX - r.size;
}

int y700_range_contains(struct y700_range a, struct y700_range b)
{
	return y700_range_valid(a) && y700_range_valid(b) &&
		b.start >= a.start && b.start + b.size <= a.start + a.size;
}

static int overlap(struct y700_range a, struct y700_range b)
{
	return a.start < b.start + b.size && b.start < a.start + a.size;
}

int y700_subtract(struct y700_range *ranges, size_t *count,
		  struct y700_range r)
{
	uint64_t end;
	size_t i;

	if (!y700_range_valid(r) || r.start + r.size > Y700_U64_MAX - 4095)
		return -1;
	end = (r.start + r.size + 4095) & ~4095ULL;
	r.start &= ~4095ULL;
	r.size = end - r.start;
	for (i = 0; i < *count; i++) {
		struct y700_range b = ranges[i];
		uint64_t top = b.start + b.size;

		if (!overlap(b, r))
			continue;
		if (r.start <= b.start && end >= top) {
			memmove(&ranges[i], &ranges[i + 1],
				(*count - i - 1) * sizeof(*ranges));
			--*count;
			--i;
		} else if (r.start <= b.start) {
			ranges[i] = (struct y700_range){end, top - end};
		} else if (end >= top) {
			ranges[i].size = r.start - b.start;
		} else {
			if (*count == Y700_MAX_RANGES)
				return -1;
			memmove(&ranges[i + 2], &ranges[i + 1],
				(*count - i - 1) * sizeof(*ranges));
			ranges[i].size = r.start - b.start;
			ranges[i + 1] = (struct y700_range){end, top - end};
			++*count;
			++i;
		}
	}
	return 0;
}

static uint64_t be64(const void *data)
{
	fdt64_t value;
	memcpy(&value, data, sizeof(value));
	return fdt64_to_cpu(value);
}

static int in_ram(const struct y700_memory *m, struct y700_range r)
{
	size_t i;
	for (i = 0; i < m->bank_count; i++)
		if (y700_range_contains(m->banks[i], r))
			return 1;
	return 0;
}

static int reg_ranges(const void *fdt, int node, struct y700_memory *m,
		      int reserve)
{
	int bytes, i;
	const char *reg = fdt_getprop(fdt, node, "reg", &bytes);

	if (!reg || bytes <= 0 || bytes % 16)
		return -1;
	for (i = 0; i < bytes; i += 16) {
		struct y700_range r = {be64(reg + i), be64(reg + i + 8)};
		size_t j;
		if (!y700_range_valid(r))
			return -1;
		if (reserve) {
			if (y700_subtract(m->free, &m->free_count, r))
				return -1;
			continue;
		}
		if ((r.start | r.size) & 4095 || m->bank_count == Y700_MAX_RANGES)
			return -1;
		for (j = 0; j < m->bank_count; j++)
			if (overlap(r, m->banks[j]))
				return -1;
		m->banks[m->bank_count++] = r;
	}
	return 0;
}

static int prop_u32(const void *fdt, int node, const char *name, uint32_t *v)
{
	int size;
	const fdt32_t *p = fdt_getprop(fdt, node, name, &size);
	if (!p || size != 4)
		return -1;
	*v = fdt32_to_cpu(*p);
	return 0;
}

static int framebuffer(const void *fdt, struct y700_memory *m)
{
	int n, size;
	const char *reg, *format;

	n = fdt_node_offset_by_compatible(fdt, -1, "simple-framebuffer");
	if (n < 0 || fdt_node_offset_by_compatible(fdt, n, "simple-framebuffer") >= 0)
		return -1;
	if (fdt_address_cells(fdt, fdt_parent_offset(fdt, n)) != 2 ||
	    fdt_size_cells(fdt, fdt_parent_offset(fdt, n)) != 2)
		return -1;
	reg = fdt_getprop(fdt, n, "reg", &size);
	if (!reg || size != 16)
		return -1;
	m->framebuffer = (struct y700_range){be64(reg), be64(reg + 8)};
	format = fdt_getprop(fdt, n, "format", &size);
	if (!format || size < 1 || size > sizeof(m->format) ||
	    format[size - 1] || (strcmp(format, "a8r8g8b8") &&
				strcmp(format, "x8r8g8b8") &&
				strcmp(format, "a8b8g8r8") &&
				strcmp(format, "x8b8g8r8")))
		return -1;
	memcpy(m->format, format, size);
	if (prop_u32(fdt, n, "width", &m->width) ||
	    prop_u32(fdt, n, "height", &m->height) ||
	    prop_u32(fdt, n, "stride", &m->stride) ||
	    m->width != 1904 || m->height != 3040 ||
	    m->stride < m->width * 4 || m->stride > 16384 ||
	    (m->stride & 3) || (m->framebuffer.start & 4095) ||
	    m->framebuffer.size > 0x8000000 ||
	    m->framebuffer.size < (uint64_t)m->stride * m->height ||
	    !in_ram(m, m->framebuffer) || overlap(m->framebuffer, m->packed) ||
	    overlap(m->framebuffer, m->fdt))
		return -1;
	return y700_subtract(m->free, &m->free_count, m->framebuffer);
}

static int parse_layout(const void *fdt, uintptr_t address,
			struct y700_range image, int lab, struct y700_memory *m)
{
	int n, chosen, bytes;
	const char *p;

	memset(m, 0, sizeof(*m));
	if (!fdt || (address & 7) || fdt_check_header(fdt) ||
	    fdt_totalsize(fdt) > Y700_FDT_MAX ||
	    fdt_check_full(fdt, fdt_totalsize(fdt)) ||
	    fdt_address_cells(fdt, 0) != 2 || fdt_size_cells(fdt, 0) != 2)
		return -1;
	if (lab) {
		if (fdt_node_check_compatible(fdt, 0, "linux,dummy-virt"))
			return -2;
	} else if (fdt_node_check_compatible(fdt, 0, "lenovo,elden")) {
		return -2;
	}
	m->fdt = (struct y700_range){address, fdt_totalsize(fdt)};
	fdt_for_each_subnode(n, fdt, 0) {
		p = fdt_getprop(fdt, n, "device_type", &bytes);
		if (p && bytes == 7 && !memcmp(p, "memory", 7) &&
		    reg_ranges(fdt, n, m, 0))
			return -3;
	}
	if (!m->bank_count || !in_ram(m, image) || !in_ram(m, m->fdt))
		return -3;
	chosen = fdt_path_offset(fdt, "/chosen");
	p = fdt_getprop(fdt, chosen, "y700,uefi-packed-range", &bytes);
	if (lab) {
		m->packed = image;
	} else {
		if (!p || bytes != 16)
			return -4;
		m->packed = (struct y700_range){be64(p), be64(p + 8)};
		if (m->packed.size > 0x8000000 || !in_ram(m, m->packed) ||
		    !y700_range_contains(m->packed, image))
			return -4;
	}
	if (!y700_range_valid(m->packed) ||
	    m->packed.start + m->packed.size > Y700_U64_MAX - 4095 ||
	    m->fdt.start + m->fdt.size > Y700_U64_MAX - 4095 ||
	    overlap(image, m->fdt) ||
	    (overlap(m->packed, m->fdt) && !y700_range_contains(m->packed, m->fdt)))
		return -4;
	memcpy(m->free, m->banks, m->bank_count * sizeof(*m->banks));
	m->free_count = m->bank_count;
	return 0;
}

int y700_probe_framebuffer(const void *fdt, uintptr_t address,
			   struct y700_range image, struct y700_memory *m)
{
	int result = parse_layout(fdt, address, image, 0, m);

	return result ? result : framebuffer(fdt, m);
}

int y700_psci_method(const void *fdt, int lab, const char **method)
{
	int node, length;
	const char *value;

	if (!method)
		return -8;
	*method = NULL;
	node = fdt_node_offset_by_compatible(fdt, -1, "arm,psci-1.0");
	if (node == -FDT_ERR_NOTFOUND)
		node = fdt_node_offset_by_compatible(fdt, -1, "arm,psci-0.2");
	if (node < 0)
		return -8;
	value = fdt_getprop(fdt, node, "method", &length);
	if (!value || length != 4 || memcmp(value, lab ? "hvc" : "smc", 4))
		return -8;
	*method = value;
	return 0;
}

int y700_parse_memory(const void *fdt, uintptr_t address,
		      struct y700_range image, int lab, struct y700_memory *m)
{
	int n, chosen, bytes, count, i;
	const char *p;
	uint64_t start, size;
	size_t j, k;
	int result = parse_layout(fdt, address, image, lab, m);

	if (result)
		return result;
	chosen = fdt_path_offset(fdt, "/chosen");
	count = fdt_num_mem_rsv(fdt);
	if (count < 0 || count > Y700_MAX_RANGES)
		return -5;
	for (i = 0; i < count; i++) {
		if (fdt_get_mem_rsv(fdt, i, &start, &size) ||
		    y700_subtract(m->free, &m->free_count,
				  (struct y700_range){start, size}))
			return -5;
	}
	n = fdt_path_offset(fdt, "/reserved-memory");
	if (n >= 0) {
		int child;
		if (fdt_address_cells(fdt, n) != 2 || fdt_size_cells(fdt, n) != 2)
			return -5;
		fdt_for_each_subnode(child, fdt, n) {
			p = fdt_getprop(fdt, child, "status", &bytes);
			if (p && bytes == 9 && !memcmp(p, "disabled", 9) &&
			    !fdt_getprop(fdt, child, "reg", NULL))
				continue;
			if (reg_ranges(fdt, child, m, 1))
				return -5;
		}
	}
	/* The original Android initrd remains live until kShimC hands off. */
	p = fdt_getprop(fdt, chosen, "linux,initrd-start", &bytes);
	if (p) {
		const char *q;
		int end_bytes;
		q = fdt_getprop(fdt, chosen, "linux,initrd-end", &end_bytes);
		if (!q || bytes != 8 || end_bytes != 8 || be64(q) <= be64(p) ||
		    y700_subtract(m->free, &m->free_count,
				  (struct y700_range){be64(p), be64(q) - be64(p)}))
			return -5;
	}
	if (!lab && framebuffer(fdt, m))
		return -6;
	for (j = 0; j < m->free_count; j++)
		if (y700_range_contains(m->free[j], image))
			break;
	if (j == m->free_count)
		return -7;
	if (y700_subtract(m->free, &m->free_count, m->packed) ||
	    y700_subtract(m->free, &m->free_count, m->fdt))
		return -7;
	/* Sort without relying on pre-relocation runtime state. */
	for (j = 1; j < m->free_count; j++)
		for (k = j; k && m->free[k].start < m->free[k - 1].start; k--) {
			struct y700_range tmp = m->free[k];
			m->free[k] = m->free[k - 1];
			m->free[k - 1] = tmp;
		}
	return m->free_count ? 0 : -7;
}
