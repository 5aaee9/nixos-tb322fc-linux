# Preparing an internal NixOS root filesystem

The build and planning tools described here prepare local artifacts for
TB322FC / elden without touching a tablet. For the staged device installer,
including backup, the Android reset, 256 GiB partitioning and verification,
follow the [complete installation guide](install.md). Android's installed
boot chain and recovery are retained. The combined installer is offline
tested and still needs a fresh end-to-end hardware acceptance.

Current persistent builds use Btrfs on the partition labelled `rootfs`,
without NBD or a RAM overlay. The direct local-root image loads through
`fastboot boot`. A separate Android-preserving installed menu chains
kShimC, a RAM UEFI provider and systemd-boot; see the
[Btrfs and installed-menu guide](btrfs.md) for its build and migration
boundaries. The provider's EFI files remain embedded in boot.img, so it
does not yet support independent disk-ESP generation updates.

The original ext4 installation on the development tablet followed an
explicitly authorized Android reset and 256 GiB allocation: 1 GiB future
ESP and 255 GiB rootfs. Two internal-root boots and an Android/Linux round
trip passed. The same
boot image loaded a second compatible NixOS userspace generation while a
password and test file persisted. This is target-device acceptance of the
local-root handoff; it is not an unattended public installer or full
kernel-generation rollback.

## Storage proposal

`tools/storage-layout.py` verifies a private capture's primary/backup GPT
headers, entry-array CRCs, repeated-read hashes, geometry and partition
bounds. It produces a JSON proposal, never a command that writes a disk:

```sh
python3 tools/storage-layout.py /private/data-lun-gpt.json \
  --linux-gib 256 --output /private/layout-256.json
```

The proposal reserves 1 GiB of the selected Linux budget for a future FAT
ESP (`linux-esp`) and assigns the remainder to `rootfs`. Its geometry is
independent of the filesystem selected by the installation archive. It preserves
userdata's starting LBA and the entries of all preceding partitions.
Captures and device GUIDs belong outside the public repository.

The tablet's Android userdata is encrypted F2FS. Free space reported by
Android is not evidence of a removable partition tail. Do not shorten GPT
before a validated encrypted-filesystem shrink, or before an explicitly
approved recreation/restore procedure. A GPT snapshot alone does not back
up Android data or its encryption state.

`tools/prepare-storage-write.py` can derive exact replacement GPT bytes
from the same capture and capacity. Its CLI writes only a private JSON
transaction. It preserves existing GUIDs/attributes, the userdata start,
unaffected entries and header geometry. Its lower-level writer is not a
complete installer: a reviewed caller must establish device identity,
unmounted state, exclusive access and the approved Android reset/shrink
procedure before providing a writable disk descriptor.

`tools/prepare-recovery-reset.py` similarly prepares a private stock BCB
request from a verified misc backup. It rejects pending recovery/merge
state and preserves vendor boot-control bytes. Use this only after
confirming the actual device's recovery format, options and wipe behavior.
For an approved userdata recreation, the reset request must be durable
before shortening GPT; otherwise an interrupted install could let Android
mount an old filesystem beyond the new partition boundary.

## Build the installation payload

Use the project's pinned stable input and public-only device configuration
from the [Nix build guide](build.md). On x86_64:

```sh
nix run .#build-aarch64 -- .#rootfs-archive \
  --override-input device-config path:/private/device-config \
  --no-write-lock-file --out-link out/persistent-rootfs
```

The output link contains `nixos-rootfs.tar.gz`, checksums, closure registration
and metadata. The Nix builder verifies the closure in an isolated store,
normalizes registration times and creates the system profile and GC root.
The tar records numeric root ownership, permissions and hardlinks. Matching
firmware remains in the board boot image. No host root privileges are needed.

Installation must extract as root while explicitly preserving
permissions, numeric ownership, ACLs and extended attributes. A non-root
host validation should use `--same-permissions --no-same-owner`: GNU tar's
default umask can otherwise change modes such as `/tmp`'s `1777`, even
when the archive records them correctly. This is an artifact-validation
detail, not an instruction to format or extract onto a tablet yet.

The repository's persistent development profile locks the initial `y700`
password and enables GNOME automatic login. Set a password through the
trusted USB root connection for authenticated local login. The exported
hardware and GNOME modules do not create this account or enable autologin.
SSH is restricted to the development USB link and host key. Real suspend
remains disabled pending a separate hardware test. These are development
installation defaults, not a release account/security policy.

## Build the local-root boot candidate

After importing matching private firmware using the Nix build guide:

```sh
nix build .#boot-persistent --out-link out/persistent-boot
```

The builder uses an isolated Nix sandbox and publishes an immutable output.
It preserves the reference board DTB and firmware, enables optional RNDIS
diagnostics and omits the NBD driver. The Android header-v4 image carries
`root=PARTLABEL=rootfs`. Do not send it to a tablet that has no approved
installation on that partition.

The initramfs rejects duplicate labels. It protects Android siblings and
other disks, checks the root filesystem using block-level read-only mode
and `ro,noload` for ext4 or `ro,rescue=nologreplay` for Btrfs, then checks the
installation contract and system profile.
Only an accepted root is reopened read/write. It retains firmware in RAM
and enters the selected profile's stage 2. Following this profile permits
compatible userspace updates; changing the board kernel still requires a
new boot image until EFI generation loading is implemented.

## Host-only validation

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
nix build .#efi-lab-tools --out-link result-efi-lab-tools
nix build .#busybox --out-link result-busybox
nix build .#gen-init-cpio --out-link result-gen-init-cpio
nix develop --command python3 tools/test-persistent-handoff.py --out out/persistent-handoff
```

The QEMU test executes the actual local-root initramfs with a generic ARM64
kernel, six synthetic SCSI disks and 4 KiB sectors. It checks retained
writes across two boots, Android sentinel protection, clean ext4 state,
and unchanged disks when rejecting duplicate roots, missing installation
contracts or invalid profiles. Its tiny stage 2 is not NixOS or GNOME.
The separate target tests have since verified UFS root mounting, GDM
startup, a normal reboot to retained Android and a second persistent
generation. The owner confirms physical power-key behavior. Standalone
poweroff and real suspend remain separate acceptance items.

## Boot an approved installation

`tools/run-usb-debug-fastboot.ps1` provides the Windows host path for an
already installed rootfs. Supply the verified boot image, its expected
SHA-256, the target fastboot serial, fastboot executable and a new private
log directory. It verifies target product, board, unlock and expected slot,
then performs a single fastboot boot and assigns a temporary address to
the identified gadget. Unlike the bring-up helper, it runs no NBD server.
It restores its temporary network configuration on disconnect; a detached
adapter can require the scoped read-only cleanup audit recorded in its
private logs. Do not apply its settings to another adapter.

With the stock boot image, normal reboot returns to installed Android and
starting Linux again requires fastboot boot. Installing the separate
Android/Linux menu changes that startup behavior. In either case,
disconnecting USB after a successful local-root boot does not remove the
root filesystem. Keep the verified boot image and matching own-tablet
firmware available for recovery.

The repository development profile enables automatic login. Initialize the
`y700` password through trusted USB access and change it for normal use. Reconnect
Wi-Fi if no private connection profile was restored. Compatible userspace
updates may select a registered system profile while retaining old
generations, but the current generic NixOS bootspec does not describe the
board kernel/initramfs. Do not publish it as an EFI entry or run a
bootloader installation based on it.
