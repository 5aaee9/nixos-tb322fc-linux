# NixOS on Lenovo Y700 Gen 4

Experimental NixOS GNOME integration for the Lenovo Legion Tab Y700 Gen 4:
**TB322FC / elden, Qualcomm SM8750, 16 GB RAM and 512 GB storage**.

The development system boots with `fastboot boot` and can use either a
temporary USB/NBD root or an installed internal ext4 root. Android and its
installed boot images are retained. The [complete installation guide](docs/public/install.md)
provides a staged Windows/WSL installer for a 256 GiB Linux allocation with an
Android data reset. The combined script is offline tested; the underlying
installation and persistent boot procedure has passed on the development
tablet. A bootloader unlock procedure is not included.

## Current status

The tested configuration uses pinned NixOS 26.05, GNOME on Wayland and the
elden kernel baseline. Kernel sources come from a fixed official Linux commit
with [device patches maintained here](vendor/tb322fc-linux/patches/kernel/README.md).
As of the November 2, 2026 tests:

| Component | Evidence |
| --- | --- |
| Temporary Linux boot and GNOME automatic login | Verified on the target tablet |
| Display, touch, Wi-Fi and speakers | Target observations and machine evidence; see the scoped status record |
| GPU | GNOME uses the MSM/GBM/EGL path; broader graphics acceptance is pending |
| Power key | System handler passes fresh-boot/injected checks; owner confirms physical button behavior |
| Firewall and USB diagnostics | Verified with the repaired kernel configuration |
| System suspend | Still disabled, including the internal-root development profile |
| Persistent Linux installation | 1 GiB future ESP + 255 GiB ext4; two boots and Android round trip pass; combined installer awaits hardware acceptance |
| OpenABL / systemd-boot | Complete offline ABL and board EFI candidates built; QEMU generation handoff passes; target authentication, recovery and EFI acceptance remain unproven |

Short power-key release toggles the display. Holding it for about two seconds
opens the existing GNOME power menu. The implementation uses udev and a
systemd-managed input reader; it does not patch GNOME source.

See [hardware status](docs/public/status.md) for the limits of each result.
The hardware matrix inside the vendored reference describes its own test
system and is not a claim that every component works on this NixOS image.

## Build and test

Follow the [build and temporary-boot guide](docs/public/build.md). You need an
already unlocked, matching tablet and its own stock firmware. Firmware
binaries, calibration, SSH keys and prebuilt images are not distributed here.

Builds use `flake-parts` with the existing pinned stable NixOS input. Kernel,
BusyBox, firmware initramfs, Android boot images, registered GNOME rootfs,
EFI bundles and bootloader experiments are Nix derivations:

```sh
nix build .#boot-usb-nbd --out-link result-boot-usb-nbd
nix run .#build-aarch64 -- .#rootfs-desktop --out-link result-rootfs
```

Import the matching own-tablet firmware first as described in the build guide.
On an ARM64 build host, `nix build .#rootfs-desktop` works directly.

The desktop development configuration accepts an external SSH public key and
creates a disposable `y700` account with automatic login and an empty local
password. It is intended for attended development on a trusted USB connection.
The USB cable and NBD server must remain available while Linux uses this rootfs.

For internal storage, follow the [complete installation workflow](docs/public/install.md)
and [persistent rootfs design](docs/public/persistent-rootfs.md). It clears
Android user data, retains Android itself, initializes a private desktop
password and verifies persistence. It does not install OpenABL/systemd-boot;
Linux still starts with `fastboot boot`.

The [OpenABL and board EFI guide](docs/public/openabl-efi.md) covers offline
kernel, generation and ESP packaging plus the native SM8750 ABL build.
The generated ABL carries only a placeholder signature and is not an
accepted tablet installation image. The [EFI lab](docs/public/efi-chain-lab.md)
documents the narrower emulator tests.

## Repository contents

- `flake.nix`, `flake.lock`, `nix/`: flake-parts modules, pinned sources,
  artifact derivations, build checks and development shell.
- `nixos/`: ARM64 userspace, board audio,
  firmware integration, USB/NBD lifecycle and power-key policy.
- `tools/`: host build helpers, read-only firmware collection, NBD server,
  staged persistent installer, serial-scoped Windows boot orchestration and
  optional offline AVB tooling.
- `vendor/tb322fc-linux/`: reference integration source, configuration,
  patches, firmware inventories and its original license notices.
- `docs/public/`: public build instructions and scoped test results.

Generated outputs, downloaded source trees, firmware, local agent state and
private investigation notes stay untracked. See the
[repository content policy](docs/public/repository.md).

## Source attribution

The reference integration snapshot is recorded at commit
`473f3e075cf328e094db3e79721fefeed248d42b`. The initial kernel patch preserves
the device support and attribution from
`GEEKiDoS/linux@b0c05eb72e10140f87efd0e499ad840e6c3e6975`. Builds fetch
the official Linux base and apply the local patch series; the third-party
kernel repository is only a provenance reference.
Exact external source pins are in
[`sources.json`](vendor/tb322fc-linux/sources.json).
The vendored [license](vendor/tb322fc-linux/LICENSE) and component notices
are retained with those files; they describe their own scope.
