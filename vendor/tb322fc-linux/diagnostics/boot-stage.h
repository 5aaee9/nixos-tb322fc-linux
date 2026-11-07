/* SPDX-License-Identifier: MIT */
#ifndef Y700_BOOT_STAGE_H
#define Y700_BOOT_STAGE_H

/* Caller validates that this is accessible scanout RAM and handles coherency.
 * Rows 0..95 belong to the shim; rows 128..223 belong to the EFI provider. */
static inline void y700_stage_glyph(uintptr_t address, uint32_t stride,
				    uint32_t row, uint32_t column, uint16_t glyph)
{
	unsigned x, y;

	for (y = 0; y < 40; ++y) {
		volatile uint32_t *pixels = (volatile uint32_t *)
			(address + (uint64_t)(row + y) * stride);
		for (x = 0; x < 24; ++x)
			if (glyph & (1u << (14 - (y / 8) * 3 - x / 8)))
				pixels[column + x] = 0x00ffffff;
	}
}

static inline int y700_stage_draw(uintptr_t address, uint64_t capacity,
				 uint32_t width, uint32_t height, uint32_t stride,
				 uint32_t row, int provider,
				 unsigned stage, int status)
{
	static const uint16_t hex[16] = {
		0x7b6f, 0x2492, 0x73e7, 0x73cf,
		0x5bc9, 0x79cf, 0x79ef, 0x7249,
		0x7bef, 0x7bcf, 0x7bed, 0x6bae,
		0x7927, 0x6b6e, 0x79e7, 0x79e4,
	};
	uint32_t digits[12], color = status ? 0x00ff00ff : 0x0000ff00;
	uint64_t span = (uint64_t)stride * height;
	unsigned x, y, i;

	if (!address || (address & 3) || width < 640 || width > 4096 ||
	    height < 224 || height > 4096 || stride < width * 4 ||
	    stride > 16384 || (stride & 3) || capacity < span ||
	    span > (uint64_t)(~(uintptr_t)0) - address ||
	    (row != 0 && row != 128))
		return -1;
	/* S/U, two hex stage digits, separator, full signed-status bit pattern. */
	digits[0] = provider ? 0x5b6f : hex[5];
	digits[1] = hex[(stage >> 4) & 15];
	digits[2] = hex[stage & 15];
	digits[3] = 0x01c0;
	for (i = 0; i < 8; ++i)
		digits[4 + i] = hex[((uint32_t)status >> ((7 - i) * 4)) & 15];
	for (y = row; y < row + 96; ++y) {
		volatile uint32_t *pixels =
			(volatile uint32_t *)(address + (uint64_t)y * stride);
		for (x = 0; x < width; ++x)
			pixels[x] = y < row + 8 ? color : 0;
	}
	for (i = 0; i < 12; ++i)
		y700_stage_glyph(address, stride, row + 24, 16 + i * 40, digits[i]);
	if (status && width >= 1280) {
		uint16_t label[15] = {0x79e7, 0x6bad, 0x6bad, 0};
		unsigned reversed[10], count = 0, length = 4;
		uint32_t magnitude = status < 0 ? 0u - (uint32_t)status : (uint32_t)status;

		if (status < 0)
			label[length++] = 0x01c0;
		do {
			reversed[count++] = magnitude % 10;
			magnitude /= 10;
		} while (magnitude);
		while (count)
			label[length++] = hex[reversed[--count]];
		for (i = 0; i < length; ++i)
			y700_stage_glyph(address, stride, row + 24, 640 + i * 40,
					  label[i]);
	}
	return 0;
}

#endif
