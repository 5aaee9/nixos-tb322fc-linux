# Validation

## Current NixOS integration

The parent project records its own
[target results](../../../docs/public/status.md). Those include a temporary
USB/NBD boot, GNOME and the system power-key handler. The following initial
assessment and reference results are historical and have different scope.

## Initial TB322FC assessment

The 2026-10-23 TB322FC/elden build used the device-specific
`firmware-tb322fc-prc.json` manifest and verified all 78 firmware files before
building. `sha256sum -c artifacts/SHA256SUMS` passed for `Image`,
`sm8750-lenovo-elden.dtb`, `kernel.config`, and `boot.img`.
`unpack_bootimg` parsed an Android header-v4 image with a 70,973,952-byte
kernel and an empty external ramdisk. The DTB is built into the kernel and all
78 manifest firmware paths are present in the built-in initramfs.

The tablet has no GPT partition named `rootfs`, so this image has not been
started by Linux and the NixOS rootfs has not been handed off to the device.
Both the unsigned USB/NBD image and an AOSP Testing key AVB candidate were
transferred with `fastboot boot`; the locked ABL rejected both before Linux
execution. No display, touch, GPU, Wi-Fi, GNOME, or kernel-runtime result is
claimed for this initial build. See [AVB history](avb.md) for the
locked-bootloader boundary.

## Repository and build

- All pinned source revisions have been fetched from their public remotes.
- The three bundled userspace patches reproduce their recorded source trees.
- The pinned wireless-regdb source supplies the exact database/signature hashes.
- The firmware importer verified and staged all 78 required files.
- The audio topology regenerated from the fetched macros matches the expected hash.
- The kernel and a static AArch64 BusyBox were built from fetched source using
  the public configuration and build script.
- The boot image uses the expected embedded DTB and an empty external ramdisk.
- The initramfs contains the current handoff script and no private executable
  payload, experiment identifier or generated diagnostic service.

`scripts/check.py` checks tracked files for private workspace paths, stale
experiment labels, broken local links and malformed source/firmware manifests.
The reference project's CI also checked source availability and patch
application. No CI workflow is supplied by this parent snapshot, and these
checks do not constitute a firmware-equipped boot test.

## Reference device results

The following results belong to the original reference validation record and
are not evidence from the current TB322FC run. That reference image booted
through the cleaned initramfs to the greeter, confirmed on its tablet. SSH then
verified the live configuration and firmware search path. All 78 firmware files
under `/run/firmware` matched their hashes. Rootfs and its parent disk remained
writable; all other enumerated UFS devices were read-only.

The same boot passed 32 display CRC samples, rear/front 16-frame captures,
three seconds of speaker playback with 30 advancing PCM observations, and
87 accelerometer, 88 gyroscope and 17 light measurements. Sensor and desktop
services started automatically. No hardware-controller retry was needed.

The image SHA256 and source/config identities are in [validation.json](../validation.json).
These results used the existing prepared rootfs. They validate the rebuilt boot
image and its handoff, not a fresh distribution installation or every userspace
build recipe.

The [support matrix](hardware.md) includes earlier functional driver tests and
their limits. No new suspend, Bluetooth discovery or charging success is
claimed for the public image.
