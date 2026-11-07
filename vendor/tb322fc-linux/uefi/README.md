# RAM UEFI provider

This directory contains the source overlay for a deliberately limited U-Boot
EFI provider. It is separate from the installed Qualcomm ABL. Build it with
the pinned Nix package; do not flash the standalone provider or RAM diagnostic.
The separate `boot-kshimc-uefi-persistent` package embeds this provider in an
Android-preserving menu image. That image requires its own AVB footer,
capacity/readback checks and reviewed installation procedure; see the
[Btrfs installation guide](../../../docs/public/btrfs.md).

Only the embedded, compressed FAT filesystem is exposed as a block device.
Environment and EFI variables are volatile. Physical storage, USB, capsules,
network boot and persistent variable backends are absent. The board imports
validated RAM and framebuffer information from kShimC, subtracts reservations
and all live input ranges before relocation, then runs the unchanged
systemd-boot EFI application.

The lab build has a separate QEMU entry contract and serial driver. Passing
the lab does not establish tablet support. Target images require the
`y700,uefi-packed-range` handoff property and a framebuffer; they do not accept
the QEMU contract.

Build the target candidate with:

```sh
nix build .#boot-kshimc-uefi-ram --out-link result-uefi-boot
nix build .#checks.x86_64-linux.uefi-memory .#checks.x86_64-linux.kshimc-menu
```

The first target payload mounts no disk filesystem. It checks the EFI
platform, systemd-boot LoaderInfo and selected-entry variables, its initrd
identity and the provider's DT marker before exposing static diagnostics
over USB. It sets all enumerated UFS nodes read-only and requests a reboot
after five minutes in userspace. That timer cannot recover an early hard
lock. Android remains the kShimC default; select `UEFI (RAM)` explicitly.

Reproduce the provider interoperability test on the host:

```sh
nix build .#uefi-lab-a --out-link result-uefi-lab
nix build .#efi-lab-tools --out-link result-efi-tools
python3 tools/test-uefi-provider.py \
  --provider result-uefi-lab \
  --qemu result-efi-tools/qemu/bin/qemu-system-aarch64 \
  --out /tmp/y700-provider-test
```

This test boots the actual lab provider with QEMU's ARM64 kernel entry.
It uses neither external EFI firmware nor an external disk. The same
provider binary runs the default entry A and a different initrd B,
selected through the real systemd-boot menu. The target build has no physical
key input in systemd-boot yet. The RAM FAT is embedded in the provider:
installed ESP access and independent NixOS generation updates remain future
work, and are not established by this diagnostic.

The first tablet trial on November 3, 2026 accepted the RAM image and
returned to stock Android. No EFI diagnostic evidence was collected.
Physical selection of the UEFI entry is not yet confirmed for that trial;
do not interpret it as either target EFI success or a proven hardware
rejection.

Later trials established the rootless EFI diagnostic on November 6 and
the installed NixOS desktop on November 7. The separately packaged menu
now boots normally from boot_a through this provider into systemd-boot
generation 3, a writable Btrfs root and automatic GNOME login. Original ABL
is retained. These results do not add disk ESP access, persistent EFI
variables or physical key input in systemd-boot.

Files added to U-Boot are GPL-2.0-or-later unless a file says otherwise.
Upstream source and licensing are retained by the Nix source input.
