# Nix builds and boot images

All board artifacts are built by the pinned flake. The flake is organized with
`flake-parts` under `nix/modules/` and `nix/packages/`; the host only needs Nix
with flakes enabled. Device operations remain separate from this build.

The target is TB322FC / `elden` (SM8750, 512 GB). Android and the stock ABL
remain the recovery path. The build never opens a tablet device and does not
write a partition.

## Prepare private inputs

The firmware and stock boot backup are private fixed-output inputs. Arrange the
matching 78 files using the manifest and import them once:

```sh
nix run .#import-device-inputs -- \
  --firmware /private/path/tb322fc-firmware \
  --stock-boot /private/path/boot_a.img
```

For an extracted stock directory that has not been arranged yet, use
`--stock-directory /private/path/extracted-stock` instead of `--firmware`.
The app builds the pinned AudioReach topology and regulatory database, finds
files by manifest hashes, and assembles the same canonical firmware archive.
Only kShimC needs `--stock-boot`; ordinary Linux builds need the firmware input.

The importer verifies every file and imports canonical archives into the Nix
store. It rejects mismatched firmware hashes, leaf symlinks and unsafe paths.
Keep calibration, serials, logs and private keys outside the repository.

A development public SSH key is supplied through a separate public-only flake
input when needed. The input is copied into the world-readable Nix store; do
not put a private key there:

```sh
nix build .#nixosConfigurations.elden-desktop.config.system.build.toplevel \
  --override-input device-config path:/private/path/device-config \
  --no-write-lock-file
```

Create `/private/path/device-config/default.nix` with
`{ debugPublicKey = "ssh-ed25519 YOUR_PUBLIC_KEY"; }` and pass the same input
override to every rootfs, system or EFI build intended for that device. The
old `Y700_DEBUG_PUBLIC_KEY_FILE` environment variable is no longer read.

The default `nix/device-config/default.nix` contains no key and installs no
root authorized key.

To integrate the device into your own NixOS configuration instead of using
these repository image profiles, import the exported `default` and `gnome`
modules. They define no normal user or automatic login and do not enable
SSH. The optional `development` export provides USB diagnostics. The
[module guide](modules.md) includes a complete consumer flake, custom-user
example and migration notes for the former `desktop` export.

AVB signing remains an explicit host-side app so private keys never enter a
Nix derivation or store: `nix run .#sign-boot-avb -- --help`. It uses pinned
avbtool/OpenSSL, takes the key and template at runtime and refuses an existing
output. An AVB signature does not override a locked ABL's fastboot policy.

## Build artifacts

Use the package names below. Sources and build tools are pinned; byte-for-byte
reproducibility of every artifact is not yet established. Firmware-containing
outputs stay private.

```sh
nix flake check --all-systems --no-build
nix flake check
nix build .#boot-usb-nbd --out-link result-boot-usb-nbd
nix build .#boot-persistent
nix build .#rootfs              # persistent Btrfs image
nix build .#rootfs-archive      # registered installation tarball
nix build .#rootfs-desktop
nix build .#efi-generation
nix build .#efi-esp
nix build .#kshimc-packer .#kshimc-runtime .#boot-kshimc
nix build .#boot-kshimc-linux-ram # Android default + Linux RAM-overlay experiment
nix build .#boot-kshimc-uefi-ram # Android default + rootless RAM EFI-chain diagnostic
nix build .#boot-kshimc-uefi-persistent # Linux default + retained Android; add AVB footer before installation
nix build .#audio-topology .#wireless-regdb
```

The outputs are directories in the Nix store. Artifact packages carry hashes
and metadata; build/check dependencies validate the Android header, ARM64
kernel/DTB, rootfs ownership,
Nix store registration, EFI readback and kShimC image layout. `.#openabl` and
`.#openabl-entry-probe` are offline experiments only; their qtestsign output is
not an OEM-authenticated ABL and must not be flashed.

For an ARM64 host, build directly. On x86_64, the `build-aarch64` app creates a
namespace-local QEMU/binfmt handler and keeps Nix sandboxing enabled. Use it
for `rootfs*`, `efi-generation`, `efi-esp` and NixOS system builds. This needs
unprivileged user/mount namespaces and a local Nix store; a daemon-only host
can instead use a configured ARM64 builder:

```sh
nix run .#build-aarch64 -- \
  .#rootfs-desktop --out-link result-rootfs
```

The old shell entry points remain compatibility wrappers around these Nix
packages. They no longer invoke a host compiler, `sudo`, or a mutable source
checkout. Prefer the flake commands above. `build-nixos-rootfs.sh` now accepts
`persistent|desktop|base` and an output directory link, rather than an arbitrary
system path and image filename. Kernel/boot wrappers accept `ARTIFACT_DIR` as
that new link; the image inside is always named `boot.img`.

## Inspect and verify

```sh
nix path-info -S .#boot-usb-nbd .#rootfs .#efi-esp
nix flake check
(cd result-boot-usb-nbd && sha256sum -c SHA256SUMS)
```

A result link points to a Nix store directory. Do not copy firmware or
calibration data from another tablet into an output.

## kShimC Linux RAM experiment

`boot-kshimc-linux-ram` retains the original Android kernel and adds a Linux
entry using `kernel-readonly`. That kernel keeps the built-in elden DT and
initramfs. It reads the existing `PARTLABEL=rootfs` installation with ext4
`ro,noload` or Btrfs `ro,rescue=nologreplay`, locks UFS block devices
read-only, and uses a disposable 2 GiB RAM overlay for writable state.
It requires an existing installation; it
does not install NixOS. The ordinary `boot-persistent` retains writable-root
behavior.

This combined image is about 111.5 MiB, larger than the 96 MiB boot partition.
It is only a `fastboot boot` candidate and must never be flashed. The packer
has a separate 128 MiB RAM policy ceiling; the original installed-image size
bound remains unchanged. A fresh device `max-download-size` measurement and
independent review of the exact image/runner are required before a test.
Neither the policy ceiling nor that measurement proves ABL placement or
hardware acceptance.

The menu defaults to Android after ten seconds. Selecting Linux tests direct
kernel handoff; it does not provide UEFI, systemd-boot, or independent kernel
generation selection. The source includes live Linux memory-range checks
and defaults back to Android on rejection.

The November 3, 2026 target trial reached the installed NixOS 26.05 GDM
greeter through this entry. SSH verified the overlay, its read-only ext4
lower mount and all 120 UFS block nodes read-only. The persistent root's
ext4 fstab caused `systemd-remount-fs` to fail on overlay, so this is
an experimental boot result, not release acceptance. The installed root
also reports pending journal recovery and directory checksum errors with
replay suppressed. A validated consistent lower filesystem is still required;
do not remount the actual partition writable to bypass this test constraint.
The combined image
used in that trial has SHA-256
`cbd09ec4a3b9e6eb0e2b8a50599bcb749c09ec7c0006dd4f64c176bdcc710e80`.

The November 6 readonly init revision supplies an overlay-only fstab under
`/run`, a runtime remount-service drop-in and early devtmpfs aliases.
An offline QEMU comparison using the actual NixOS stage2, activation and
systemd reproduces the old remount failure and passes with the correction;
all six synthetic disk hashes remain unchanged. This RAM-test contract
does not activate additional installed fstab mounts. The initial rootfs
health inspection stopped target testing because recovery and orphan flags
were pending. After the separately authorized November 7 on-device repair,
the corrected init reached NixOS/GNOME through UEFI. The init correction
itself does not repair or establish filesystem consistency; see the
[dated hardware results](status.md).

The current board driver shares the USB data controller between sockets
and prioritizes the long edge. Keeping the long-edge computer/debug cable
attached can prevent short-edge OTG enumeration. The owner confirmed a
short-edge mouse works after detaching the long-edge computer cable.
Keyboard operation and simultaneous data use of both sockets are not
established.

## Temporary fastboot test

The separate `boot-kshimc-uefi-ram` experiment uses a source-built U-Boot
RAM provider, the unmodified pinned systemd-boot EFI application and an
external EFI kernel/initrd. It does not replace ABL. Its provider has no
physical storage or persistent-variable backend. The first initrd mounts
no physical filesystem; its purpose is proving EFI handoff, not starting
NixOS or installing an ESP. The actual provider has passed A/B entry
selection in QEMU; this alone is not tablet acceptance.

The first tablet trial accepted the RAM image and returned to Android
without EFI diagnostic evidence. A later trial proved the rootless EFI
chain, followed by the November 7 NixOS/GNOME test using an installed root
under a RAM overlay. These are separate candidates and acceptance results;
see the [tested configuration](status.md).

See `vendor/tb322fc-linux/uefi/README.md` for provider builds and host
interoperability testing. The candidate is always RAM-only, including when
its byte count fits the boot partition. Do not pass it to the NBD helper:
its rootless diagnostic serves evidence directly over USB and returns via
a five-minute userspace timer. Review its exact image and test orchestration
before a single serial-scoped `fastboot boot`.

Only after the exact image and rootfs have been reviewed, use the existing
serial-scoped Windows helper:

```powershell
.\tools\run-usb-nbd-fastboot.ps1 `
  -BootImage .\result-boot-usb-nbd\boot.img `
  -RootfsImage .\result-rootfs\nixos-rootfs.ext4 `
  -FastbootSerial $DeviceSerial `
  -ExpectedSlot a `
  -LogDirectory "$env:TEMP\y700-usb-nbd-test"
```

This path uses one `fastboot boot`, a read-only host NBD export and a temporary
USB network. It does not flash, erase, change slots or alter Android. Keep the
NBD server running until the tablet returns to Android.
