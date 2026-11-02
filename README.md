# NixOS on Lenovo Y700 Gen 4

Experimental NixOS GNOME integration for the Lenovo Legion Tab Y700 Gen 4:
**TB322FC / elden, Qualcomm SM8750, 16 GB RAM and 512 GB storage**.

The development system boots with `fastboot boot`, reads its root filesystem
from a host-side USB RNDIS/NBD export, and writes session changes to a RAM
overlay. Android and its installed boot images are retained. This repository
does not provide a partition installer or a bootloader unlock procedure.

## Current status

The tested configuration uses pinned NixOS 26.05, GNOME on Wayland and the
elden kernel baseline. Kernel sources come from a fixed official Linux commit
with [device patches maintained here](vendor/tb322fc-linux/patches/kernel/README.md).
As of the November 1, 2026 test:

| Component | Evidence |
| --- | --- |
| Temporary Linux boot and GNOME automatic login | Verified on the target tablet |
| Display, touch, Wi-Fi and speakers | Target observations and machine evidence; see the scoped status record |
| GPU | GNOME uses the MSM/GBM/EGL path; broader graphics acceptance is pending |
| Power key | System handler passes injected short/long events and fresh-boot tests; physical button acceptance is pending |
| Firewall and USB diagnostics | Verified with the repaired kernel configuration |
| System suspend | Disabled while USB supplies the root filesystem |
| Persistent Linux installation | Not implemented; Android storage is retained |

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

The desktop development configuration requires an external SSH public key and
creates a disposable `y700` account with automatic login and an empty local
password. It is intended for attended development on a trusted USB connection.
The USB cable and NBD server must remain available while Linux uses this rootfs.

## Repository contents

- `flake.nix`, `flake.lock`, `nixos/`: pinned ARM64 userspace, board audio,
  firmware integration, USB/NBD lifecycle and power-key policy.
- `tools/`: host build helpers, read-only firmware collection, NBD server,
  serial-scoped Windows boot orchestration and optional offline AVB tooling.
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
