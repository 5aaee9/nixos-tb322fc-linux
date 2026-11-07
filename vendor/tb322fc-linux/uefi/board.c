/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <config.h>
#include <asm/armv8/mmu.h>
#include <asm/global_data.h>
#include <asm/sections.h>
#include <asm/system.h>
#include <blkmap.h>
#include <command.h>
#include <cpu_func.h>
#include <dm.h>
#include <env.h>
#include <fdtdec.h>
#include <fdt_support.h>
#include <fs.h>
#include <gzip.h>
#include <init.h>
#include <lmb.h>
#include <linux/arm-smccc.h>
#include <linux/delay.h>
#include <linux/psci.h>
#include <linux/sizes.h>
#include <malloc.h>
#include <video.h>
#include "memory.h"
#include "payload-size.h"
#include "boot-stage.h"

DECLARE_GLOBAL_DATA_PTR;
extern char y700_ramfs_start[], y700_ramfs_end[];
extern uintptr_t y700_incoming_fdt;

/* These must survive the pre-relocation BSS clear. */
static struct y700_memory memory __section(".data") = {0};
static unsigned char control_fdt[0x10000] __aligned(8) __section(".data") = {0};
static struct mm_region regions[Y700_MAX_RANGES + 5] __section(".data") = {{0}};
struct mm_region *mem_map = regions;
static struct {
	uintptr_t base;
	uint64_t size;
	uint32_t width, height, stride;
	bool ready;
} early_fb __section(".data") = {0};

/* Before DM or caches, use only the independently validated scanout RAM. */
static void y700_early_stage(unsigned stage, int status)
{
	if (early_fb.ready && !dcache_status() &&
	    !y700_stage_draw(early_fb.base, early_fb.size, early_fb.width,
			     early_fb.height, early_fb.stride, 128, 1, stage, status))
		asm volatile("dsb sy" ::: "memory");
}

static void y700_stage_paint(unsigned stage, int status)
{
	struct udevice *video;
	struct video_priv *priv;

	if (uclass_get_device(UCLASS_VIDEO, 0, &video))
		return;
	priv = dev_get_uclass_priv(video);
	if (!priv || priv->bpix != VIDEO_BPP32)
		return;
	if (y700_stage_draw((uintptr_t)priv->fb, priv->fb_size,
			    priv->xsize, priv->ysize, priv->line_length,
			    128, 1, stage, status))
		return;
	video_damage(video, 0, 128, priv->xsize, 96);
	video_sync(video, true);
}

static void __noreturn early_refuse(int code)
{
	struct arm_smccc_res result;

	y700_early_stage(0x0f, code);
	/* No writes to PMIC reboot-reason, misc, variables or storage. */
	if (IS_ENABLED(CONFIG_Y700_RAM_LAB)) {
		const char *s = "Y700_UEFI_EARLY_REFUSAL\n";
		volatile unsigned int *uart = (void *)0x09000000;
		while (*s)
			*uart = *s++;
		*uart = '0' + (-code % 10);
		*uart = '\n';
		arm_smccc_hvc(PSCI_0_2_FN_SYSTEM_OFF, 0, 0, 0, 0, 0, 0, 0, &result);
	} else {
		/* Diagnostic observation window, not a retry or a recovery watchdog. */
		__udelay(6000000);
		arm_smccc_smc(PSCI_0_2_FN_SYSTEM_RESET, 0, 0, 0, 0, 0, 0, 0, &result);
	}
	hang();
}

static void need(int result)
{
	if (result < 0)
		early_refuse(result);
}

int board_fdt_blob_setup(void **fdtp)
{
	void *incoming = (void *)y700_incoming_fdt;
	uint64_t image_size;
	int node, chosen, serial, psci;
	size_t i;
	fdt64_t regs[Y700_MAX_RANGES * 2];
	const char *method;

	memcpy(&image_size, _start + 16, sizeof(image_size));
	if (!IS_ENABLED(CONFIG_Y700_RAM_LAB) &&
	    !y700_probe_framebuffer(incoming, (uintptr_t)incoming,
				    (struct y700_range){(uintptr_t)_start, image_size},
				    &memory)) {
		early_fb.base = memory.framebuffer.start;
		early_fb.size = memory.framebuffer.size;
		early_fb.width = memory.width;
		early_fb.height = memory.height;
		early_fb.stride = memory.stride;
		early_fb.ready = true;
		y700_early_stage(1, 0);
	}
	need(y700_parse_memory(incoming, (uintptr_t)incoming,
			      (struct y700_range){(uintptr_t)_start, image_size},
			      IS_ENABLED(CONFIG_Y700_RAM_LAB), &memory));
	y700_early_stage(2, 0);
	need(y700_psci_method(incoming, IS_ENABLED(CONFIG_Y700_RAM_LAB), &method));
	need(fdt_create_empty_tree(control_fdt, sizeof(control_fdt)));
	need(fdt_setprop_u32(control_fdt, 0, "#address-cells", 2));
	need(fdt_setprop_u32(control_fdt, 0, "#size-cells", 2));
	need(fdt_setprop_string(control_fdt, 0, "compatible", "lenovo,y700-ram-uefi"));
	need(fdt_setprop_string(control_fdt, 0, "model", "TB322FC RAM UEFI provider"));
	node = fdt_add_subnode(control_fdt, 0, "memory");
	need(node);
	need(fdt_setprop_string(control_fdt, node, "device_type", "memory"));
	for (i = 0; i < memory.free_count; i++) {
		regs[2 * i] = cpu_to_fdt64(memory.free[i].start);
		regs[2 * i + 1] = cpu_to_fdt64(memory.free[i].size);
	}
	need(fdt_setprop(control_fdt, node, "reg", regs, memory.free_count * 16));
	chosen = fdt_add_subnode(control_fdt, 0, "chosen");
	need(chosen);
	serial = fdt_add_subnode(control_fdt, 0, "serial");
	need(serial);
	if (IS_ENABLED(CONFIG_Y700_RAM_LAB)) {
		fdt64_t reg[] = {cpu_to_fdt64(0x09000000), cpu_to_fdt64(0x1000)};
		need(fdt_setprop_string(control_fdt, serial, "compatible", "arm,pl011"));
		need(fdt_setprop(control_fdt, serial, "reg", reg, sizeof(reg)));
		need(fdt_setprop_u32(control_fdt, serial, "clock-frequency", 24000000));
	} else {
		need(fdt_setprop_string(control_fdt, serial, "compatible", "nulldev-serial"));
	}
	chosen = fdt_path_offset(control_fdt, "/chosen");
	need(fdt_setprop_string(control_fdt, chosen, "stdout-path", "/serial"));
	psci = fdt_add_subnode(control_fdt, 0, "psci");
	need(psci);
	need(fdt_setprop_string(control_fdt, psci, "compatible", "arm,psci-0.2"));
	need(fdt_setprop_string(control_fdt, psci, "method", method));
	if (!IS_ENABLED(CONFIG_Y700_RAM_LAB)) {
		fdt64_t reg[] = {cpu_to_fdt64(memory.framebuffer.start),
				cpu_to_fdt64(memory.framebuffer.size)};
		node = fdt_add_subnode(control_fdt, 0, "framebuffer");
		need(node);
		need(fdt_setprop_string(control_fdt, node, "compatible", "simple-framebuffer"));
		need(fdt_setprop(control_fdt, node, "reg", reg, sizeof(reg)));
		need(fdt_setprop_u32(control_fdt, node, "width", memory.width));
		need(fdt_setprop_u32(control_fdt, node, "height", memory.height));
		need(fdt_setprop_u32(control_fdt, node, "stride", memory.stride));
		need(fdt_setprop_string(control_fdt, node, "format", memory.format));
		need(fdt_setprop_u32(control_fdt, node, "rot", 3));
	}
	gd->ram_base = memory.free[0].start;
	for (i = memory.free_count; i; i--)
		if (memory.free[i - 1].size >= SZ_512M) {
			gd->ram_size = memory.free[i - 1].start +
				       memory.free[i - 1].size - gd->ram_base;
			break;
		}
	if (!i)
		early_refuse(-9);
	*fdtp = control_fdt;
	y700_early_stage(3, 0);
	return 0;
}

int dram_init(void)
{
	return 0;
}

int dram_init_banksize(void)
{
	size_t i;
	for (i = 0; i < memory.free_count; i++) {
		gd->dram[i].start = memory.free[i].start;
		gd->dram[i].size = memory.free[i].size;
	}
	return 0;
}

static void map(size_t index, struct y700_range r, uint64_t attrs)
{
	regions[index] = (struct mm_region){
		.virt = r.start, .phys = r.start, .size = r.size, .attrs = attrs
	};
}

u64 get_page_table_size(void)
{
	return SZ_2M;
}

void enable_caches(void)
{
	const uint64_t normal = PTE_BLOCK_MEMTYPE(MT_NORMAL) | PTE_BLOCK_INNER_SHARE;
	size_t i;
	struct y700_range original_fdt = memory.fdt;
	struct y700_range packed = memory.packed;

	for (i = 0; i < memory.free_count; i++)
		map(i, memory.free[i], normal);
	packed.size += packed.start & 4095;
	packed.start &= ~4095ULL;
	packed.size = ALIGN(packed.size, 4096);
	map(i++, packed, normal);
	original_fdt.size += original_fdt.start & 4095;
	original_fdt.start &= ~4095ULL;
	original_fdt.size = ALIGN(original_fdt.size, 4096);
	if (!y700_range_contains(packed, original_fdt))
		map(i++, original_fdt, normal);
	if (IS_ENABLED(CONFIG_Y700_RAM_LAB))
		map(i++, (struct y700_range){0x09000000, 4096},
		    PTE_BLOCK_MEMTYPE(MT_DEVICE_NGNRNE) |
		    PTE_BLOCK_NON_SHARE | PTE_BLOCK_PXN | PTE_BLOCK_UXN);
	/* simplefb maps its single validated scanout region when probed. */
	memset(&regions[i], 0, sizeof(regions[i]));
	icache_enable();
	dcache_enable();
}

int board_init(void)
{
	return 0;
}

int board_late_init(void)
{
	phys_addr_t ramfs, load;
	unsigned long compressed = y700_ramfs_end - y700_ramfs_start;
	struct udevice *block;
	int ret;

	/* Video probing registers stdio; board_init() is too early for that. */
	y700_stage_paint(4, 0);
	printf("Y700_RAM_UEFI_PROVIDER=v1 mode=%s physical-storage=absent variables=volatile\n",
	       IS_ENABLED(CONFIG_Y700_RAM_LAB) ? "qemu-lab" : "tb322fc");
	env_set("stdin", "serial");
	env_set("stdout", IS_ENABLED(CONFIG_Y700_RAM_LAB) ? "serial" : "vidconsole");
	env_set("stderr", IS_ENABLED(CONFIG_Y700_RAM_LAB) ? "serial" : "vidconsole");
	y700_stage_paint(5, 0);
	ret = lmb_alloc_mem(LMB_MEM_ALLOC_ANY, SZ_2M, &ramfs,
			    Y700_RAMFS_SIZE, LMB_NOOVERWRITE);
	if (ret) {
		y700_stage_paint(5, ret);
		goto failed;
	}
	if (gunzip((void *)ramfs, Y700_RAMFS_SIZE,
		   (unsigned char *)y700_ramfs_start, &compressed) ||
	    compressed != Y700_RAMFS_SIZE) {
		ret = -EINVAL;
		y700_stage_paint(6, ret);
		goto failed;
	}
	y700_stage_paint(6, 0);
	ret = blkmap_create_ramdisk("y700-ram", ramfs, Y700_RAMFS_SIZE, &block);
	if (ret) {
		y700_stage_paint(7, ret);
		goto failed;
	}
	ret = lmb_alloc_mem(LMB_MEM_ALLOC_ANY, SZ_2M, &load, SZ_4M, LMB_NONE);
	if (ret) {
		y700_stage_paint(8, ret);
		goto failed;
	}
	env_set_hex("y700_loader", load);
	y700_stage_paint(8, 0);
	env_set_hex("y700_os_fdt", memory.fdt.start);
	return 0;
failed:
	printf("Y700_UEFI_LATE_FAILURE=%d\n", ret);
	if (!IS_ENABLED(CONFIG_Y700_RAM_LAB))
		__udelay(6000000);
	reset_cpu();
	hang();
}

static int do_y700boot(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	int status;
	loff_t loader_bytes;
	void *fdt = (void *)(uintptr_t)memory.fdt.start;

	printf("Y700_UEFI_START_SYSTEMD_BOOT\n");
	y700_stage_paint(9, 0);
	/* This marker is emitted by the executing provider, not the packer. */
	status = 0;
	if (!IS_ENABLED(CONFIG_Y700_RAM_LAB))
		status = fdt_setprop_inplace(fdt, fdt_path_offset(fdt, "/chosen"),
					    "y700,uefi-provider", "ram-v1", 7);
	if (status) {
		y700_stage_paint(9, status);
		goto reset;
	}
	status = fs_set_blk_dev("blkmap", "0:0", FS_TYPE_FAT);
	if (!status)
		status = fs_size("/EFI/BOOT/BOOTAA64.EFI", &loader_bytes);
	if (!status && (loader_bytes < 64 || loader_bytes > SZ_4M))
		status = -EINVAL;
	fs_close();
	if (status) {
		y700_stage_paint(0x0a, status);
		goto reset;
	}
	y700_stage_paint(0x0a, 0);
	status = run_command("load blkmap 0:0 ${y700_loader} /EFI/BOOT/BOOTAA64.EFI 0x400000", 0);
	if (status) {
		y700_stage_paint(0x0b, status);
		goto reset;
	}
	y700_stage_paint(0x0b, 0);
	status = run_command("bootefi ${y700_loader} ${y700_os_fdt}", 0);
	y700_stage_paint(0x0c, status);
reset:
	printf("Y700_UEFI_RETURN status=%d; resetting to stock boot path\n", status);
	if (!IS_ENABLED(CONFIG_Y700_RAM_LAB))
		__udelay(6000000);
	run_command("reset", 0);
	return CMD_RET_FAILURE;
}

U_BOOT_CMD(y700boot, 1, 0, do_y700boot, "Start embedded systemd-boot from RAM", "");
