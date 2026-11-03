# Build

This vendored integration now builds through the parent project's pinned
Nix flake. Follow the [complete Nix build guide](../../../docs/public/build.md)
from the project root. The shell scripts in `scripts/` delegate to the same
derivations; they no longer download compilers or compile mutable checkouts.

## Inputs and tools

Nix supplies the kernel toolchain, static AArch64 BusyBox, gen_init_cpio,
mkbootimg, topology tools and filesystem packagers. `flake.lock` pins public
sources and tooling; `sources.json` and the local patch manifests bind the
board baseline. The kernel builder checks both the original and patched Git
trees before compiling.

Import this tablet's own matching firmware once:

```sh
nix run .#import-device-inputs -- \
  --stock-directory /private/path/extracted-stock
```

The importer builds the pinned AudioReach topology and regulatory database,
finds the stock files by hash, and validates the complete 78-file manifest.
For an already arranged directory, use `--firmware` instead. Firmware,
calibration and stock backups are not public source inputs.

`scripts/fetch-sources.py` remains an optional development-checkout helper.
Its downloaded trees are not consumed by the Nix builds.

## Kernel, initramfs and boot images

```sh
nix build .#initramfs-usb-nbd
nix build .#boot-usb-nbd --out-link out/boot-usb-nbd
nix build .#boot-persistent --out-link out/boot-persistent
nix build .#kernel-efi --out-link out/kernel-efi
```

Each boot output directory contains `boot.img`, the kernel, metadata and
`SHA256SUMS`. The two Android header-v4 images embed their DTB and initramfs
in the kernel; the external Android ramdisk is empty. Do not append a second
DTB. The persistent image requires an installed `PARTLABEL=rootfs`; the
USB/NBD image uses the separate host-delivered maintenance root.

The EFI kernel uses the separate external-initrd/DTB contract documented in
the [board EFI guide](../../../docs/public/openabl-efi.md).

Build parallelism is controlled with Nix's `--cores` and `--max-jobs`.
Compatibility wrappers accept `ARTIFACT_DIR` as a **new output link** rather
than a mutable build directory. Prefer the explicit flake commands above.

## Validation and device testing

```sh
nix flake check --all-systems --no-build
nix flake check
(cd out/boot-usb-nbd && sha256sum -c SHA256SUMS)
```

The build validates source trees, configuration, ARM64/DTB and Android header
layout. Successful compilation does not establish hardware acceptance or
byte-identical rebuilding. The Android version/date fields reproduce the
packing layout and do not describe the Linux security-patch level.

Device operations remain separate. Follow the serial-scoped temporary-boot
procedure in the [project guide](../../../docs/public/build.md#temporary-fastboot-test)
only after reviewing the exact image and matching rootfs.
