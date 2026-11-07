# Btrfs root and installed Android/Linux menu

The persistent NixOS profile uses Btrfs at `PARTLABEL=rootfs`, with `noatime`
and `compress=zstd:1`. The hardware module's filesystem defaults can still
be overridden by a consumer. The repository's USB/NBD maintenance profiles
continue to use ext4 images.

The persistent development profile enables GNOME autologin for its existing
`y700` account. The exported hardware and GNOME modules create no such user
and do not enable autologin.

## Build outputs

`nix build .#rootfs` produces `nixos-rootfs.btrfs`. The registered tar archive
from `.#rootfs-archive` records its filesystem type for the fresh installer.
That installer remains a destructive first-install procedure and must not
be run to migrate an existing Linux installation.

`nix build .#boot-kshimc-uefi-persistent` produces an Android-header-v4 boot
payload with the exact own-device stock Android kernel, kShimC, a RAM UEFI
provider, systemd-boot, and a persistent Linux generation. Linux is the menu
default after ten seconds; the Android entry remains selectable.
The output is checked against the 96 MiB partition capacity, reserving space
for a fresh AVB footer. Add and verify that footer with `.#sign-boot-avb`
before installation. Do not flash a RAM-only image or the direct Linux-only
`boot-persistent` image as an Android-preserving menu.

The provider embeds its EFI files in the boot payload. It does not yet load
new generations from the disk ESP: upgrading those embedded boot files still
requires rebuilding and reinstalling the boot image. Stock ABL is retained.

## Target result on November 7, 2026

The existing 255 GiB root was converted, and all 171,510 original
regular-file hashes passed. The conversion rollback subvolume is retained.
The signed menu was installed in `boot_a` with complete readback verification.
Normal boot reaches systemd-boot generation 3, writable Btrfs and automatic
GNOME Wayland login, without NBD or an overlay. Btrfs device error counters
and failed system services are zero. Protected Android/ABL images, GPT
edges and the unused ESP match their pre-install hashes.

See [the status record](status.md) for the tested image hash and remaining
hardware limits. This is a checked migration of the existing tablet; it
does not establish hardware acceptance of the combined fresh installer.

## Migrating an existing ext4 installation

Use a separate, known-working maintenance system with the internal rootfs
unmounted, including in other mount namespaces. Before changing it, preserve
a complete logical backup with numeric owners, ACLs and xattrs, a current
boot-partition backup, and partition-table/Android-image checksums.

On a clean source filesystem, `btrfs-convert --uuid copy --copy-label` retains
the existing files and an `ext2_saved` rollback subvolume. Check the source
with `e2fsck` first, then perform `btrfs check --readonly` and compare file
checksums after conversion. Keep the rollback subvolume; do not balance or
defragment while rollback is required. Rollback restores the old filesystem
state, not changes made after conversion.

Deploy a NixOS generation with a Btrfs fstab and a matching Btrfs-aware
initrd before installing the boot image. The initrd recognizes ext4 and
Btrfs, inspects them with recovery disabled, and only then enables writes
to the approved root partition. A read-only test continues to keep every
UFS node read-only under its RAM overlay. This kernel requires the Btrfs
inspection option `ro,rescue=nologreplay`; standalone `nologreplay` is
rejected before the filesystem is mounted.

Installation must target only the verified active `boot_a` partition and
be followed by a complete readback hash. This tablet's installation uses
the maintenance Linux environment. Do not change ABL, slot selection, GPT
or other Android partitions. Confirm normal installed boot,
the selected system generation, writable Btrfs root and desktop login.
