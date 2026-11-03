# ARM64 EFI chain lab

The intended portable boot interface is an EFI provider, systemd-boot and
standard Boot Loader Specification entries or unified kernel images.
The board-specific EFI provider and Android return path still require
TB322FC validation. This lab does not install a bootloader or operate a tablet.

For the separate board kernel, real firmware initrds, generation packaging
and native OpenABL candidate, see the [OpenABL / board EFI guide](openabl-efi.md).
Its fuller handoff test uses a one-shot reboot cycle; the original generic
lab described here runs two independent default selections.

The lab uses the existing stable nixpkgs revision in `flake.lock`.
It runs ARM64 EDK2 and unchanged systemd-boot in host QEMU, then loads a
generic ARM64 Linux EFI-stub image and one of two distinguishable initramfs
payloads. The two runs change the default BLS entry on a host-side FAT image;
firmware, systemd-boot and the test kernel remain identical.

Build host tools:

```sh
nix build .#efi-lab-tools --out-link result-efi-lab-tools
nix build .#busybox --out-link result-busybox
nix build .#gen-init-cpio --out-link result-gen-init-cpio
```

The Nix outputs supply static ARM64 BusyBox and native `gen_init_cpio`.
Their hashes are included in the evidence. Override their locations with
`--busybox` and `--gen-init-cpio` when using different output links. No
tablet firmware is included in the lab initramfs.

Run with a new output directory:

```sh
nix develop --command python3 tools/test-efi-chain.py --out out/efi-chain-lab
```

Add `--kernel out/efi-kernel/Image` to use a built board EFI kernel
instead of the generic lab kernel. The initramfs payloads in this basic
test remain minimal markers, not NixOS systems or firmware-bearing bundles.

The harness refuses to reuse an output directory. It creates only regular
host files, runs QEMU with no network and a read-only FAT boot disk, and
keeps the firmware variable store in an isolated host file. It never invokes
ADB, fastboot, a partition writer or a host block-device tool.

Acceptance checks:

- Both selected entries reach their own initramfs marker.
- Linux runs as AArch64 with a 64-bit EFI environment.
- `LoaderInfo` identifies systemd-boot.
- `LoaderEntrySelected` and kernel command-line markers match each entry.
- Both virtual machines power off normally.
- Firmware, loader and kernel input hashes remain unchanged.

The output includes serial logs, per-entry initramfs and FAT images, and
`metadata.json` with hashes, durations and outcomes. Treat these as
interoperability results only: they do not establish NixOS generation
activation, board UEFI support, UFS access, display/input, Android return,
or an installation procedure.
