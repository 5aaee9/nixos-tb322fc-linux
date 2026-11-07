/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "boot-stage.h"

static uint32_t pixels[225][1920];
static uint32_t saved[225][1920];

static uint16_t read_glyph(unsigned row, unsigned column)
{
	uint16_t bits = 0;
	for (unsigned y = 0; y < 5; ++y)
		for (unsigned x = 0; x < 3; ++x)
			bits = (bits << 1) |
				(pixels[row + y * 8 + 4][column + x * 8 + 4] == 0x00ffffff);
	return bits;
}

static void decimal_error(int status, const char *expected)
{
	static const uint16_t decimal[] = {
		0x7b6f, 0x2492, 0x73e7, 0x73cf, 0x5bc9,
		0x79cf, 0x79ef, 0x7249, 0x7bef, 0x7bcf,
	};
	assert(!y700_stage_draw((uintptr_t)pixels, sizeof(pixels),
			       1904, 224, sizeof(pixels[0]), 128, 1, 0x0f, status));
	for (unsigned i = 0; expected[i]; ++i) {
		uint16_t glyph;
		switch (expected[i]) {
		case 'E': glyph = 0x79e7; break;
		case 'R': glyph = 0x6bad; break;
		case ' ': glyph = 0; break;
		case '-': glyph = 0x01c0; break;
		default:
			assert(expected[i] >= '0' && expected[i] <= '9');
			glyph = decimal[expected[i] - '0'];
		}
		assert(read_glyph(152, 640 + i * 40) == glyph);
	}
	assert(read_glyph(152, 640 + strlen(expected) * 40) == 0);
}

int main(void)
{
	memset(pixels, 0xa5, sizeof(pixels));
	memcpy(saved, pixels, sizeof(pixels));
	assert(!y700_stage_draw((uintptr_t)pixels, sizeof(pixels),
			       640, 224, sizeof(pixels[0]), 0, 0, 7, 0));
	assert(pixels[0][0] == 0x0000ff00);
	for (unsigned y = 0; y < 225; ++y)
		for (unsigned x = 0; x < 1920; ++x)
			if (y >= 96 || x >= 640)
				assert(pixels[y][x] == saved[y][x]);
	memcpy(saved, pixels, sizeof(pixels));
	assert(!y700_stage_draw((uintptr_t)pixels, sizeof(pixels),
			       640, 224, sizeof(pixels[0]), 128, 1, 0x12, INT_MIN));
	assert(pixels[128][0] == 0x00ff00ff);
	for (unsigned y = 0; y < 225; ++y)
		for (unsigned x = 0; x < 1920; ++x)
			if (y < 128 || y >= 224 || x >= 640)
				assert(pixels[y][x] == saved[y][x]);
	memcpy(saved, pixels, sizeof(pixels));
	assert(y700_stage_draw((uintptr_t)pixels, 16, 640, 224,
			      sizeof(pixels[0]), 128, 1, 1, -1));
	assert(y700_stage_draw((uintptr_t)pixels, sizeof(pixels), 640, 223,
			      sizeof(pixels[0]), 128, 1, 1, -1));
	assert(y700_stage_draw((uintptr_t)pixels + 1, sizeof(pixels), 640, 224,
			      sizeof(pixels[0]), 128, 1, 1, -1));
	assert(y700_stage_draw((uintptr_t)pixels, sizeof(pixels), UINT_MAX, 224,
			      sizeof(pixels[0]), 128, 1, 1, -1));
	assert(y700_stage_draw((uintptr_t)pixels, sizeof(pixels), 640, 224,
			      sizeof(pixels[0]), 127, 1, 1, -1));
	assert(!memcmp(saved, pixels, sizeof(pixels)));
	decimal_error(-8, "ERR -8");
	decimal_error(-5, "ERR -5");
	decimal_error(INT_MIN, "ERR -2147483648");
	decimal_error(INT_MAX, "ERR 2147483647");
	assert(!y700_stage_draw((uintptr_t)pixels, sizeof(pixels),
			       1279, 224, sizeof(pixels[0]), 128, 1, 0x0f, -8));
	assert(read_glyph(152, 640) == 0);
	assert(!y700_stage_draw((uintptr_t)pixels, sizeof(pixels),
			       1904, 224, sizeof(pixels[0]), 128, 1, 0x0f, 0));
	assert(read_glyph(152, 640) == 0);
	puts("Boot-stage renderer: bounds, padding, isolated rows and decimal error pixels pass");
	return 0;
}
