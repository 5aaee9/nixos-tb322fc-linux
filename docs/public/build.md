# Nix build and temporary boot

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
nix build .#rootfs              # persistent ext4 image
nix build .#rootfs-archive      # registered installation tarball
nix build .#rootfs-desktop
nix build .#efi-generation
nix build .#efi-esp
nix build .#kshimc-packer .#kshimc-runtime .#boot-kshimc
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

## Temporary fastboot test

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
