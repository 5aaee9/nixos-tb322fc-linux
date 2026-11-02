# Build and temporary boot

Run Linux build commands from this repository's root unless a step explicitly
changes directory. This guide targets TB322FC / elden with SM8750 and 512 GB
storage. The Windows boot helper checks the corresponding 16+512 board identity.
It is not a generic guide for other Y700 generations.

## Host and inputs

Use a Linux build host with Nix, Bash, Python 3.11 or later, Git, e2fsprogs,
util-linux, a C compiler and the
[kernel build dependencies](../../vendor/tb322fc-linux/docs/build.md#host-dependencies).
The ARM64 userspace helper additionally needs `qemu-aarch64` at
`/usr/bin/qemu-aarch64`, unprivileged user/mount namespaces and namespace-local
binfmt support. This path has been exercised on the development Linux host;
other host distributions may require equivalent setup.

The tablet must already allow `fastboot boot`. Keep its Android recovery path
and backups. Bootloader unlocking, data resets, repartitioning and persistent
installation are outside this guide.

Fetch only the pinned sources needed for this boot/rootfs:

```sh
python3 vendor/tb322fc-linux/scripts/fetch-sources.py \
  kernel audioreach-topology wireless-regdb
```

Existing source directories are deliberately not reset or overwritten.

## Firmware

Extract the matching stock firmware from your own tablet, preserving its
directory layout. See the
[firmware input locations](../../vendor/tb322fc-linux/docs/firmware.md).
Do not use another device's calibration. Keep extraction logs and any unique
device data outside the repository.

Build the audio topology and import against the TB322FC manifest:

```sh
(
  cd vendor/tb322fc-linux
  mkdir -p build/audio
  m4 -I sources/audioreach-topology rootfs/audio/topology.m4 \
    > build/audio/topology.conf
  alsatplg -c build/audio/topology.conf \
    -o build/audio/Lenovo-Y700-Gen4-tplg.bin
  python3 scripts/import-firmware.py \
    --manifest firmware-tb322fc-prc.json \
    inputs/stock build/audio sources/wireless-regdb
)
```

`inputs/stock` is the location for the extracted firmware tree in this
example. The importer requires all 78 expected hashes before copying anything.
It refuses conflicting existing payloads. A mismatch means the stock build
or generated input needs investigation; do not bypass checksum validation.

## Boot image

```sh
bash vendor/tb322fc-linux/scripts/build-boot-usb-nbd.sh
(
  cd vendor/tb322fc-linux/artifacts
  sha256sum -c USB-NBD-SHA256SUMS
)
```

This builds the USB/NBD command line, firewall support and embedded firmware
into an Android header-v4 image at
`vendor/tb322fc-linux/artifacts/boot-usb-nbd.img`.
The older `build-boot.sh` default image expects a prepared
`PARTLABEL=rootfs` partition and is not suitable for this no-write test.

## NixOS desktop rootfs

Create a dedicated SSH key outside the repository, or use an existing
development key. Never place the private key in an image or in Git.

```sh
key_dir="$HOME/.local/state/y700-debug"
install -d -m 700 "$key_dir"
ssh-keygen -t ed25519 -f "$key_dir/id_ed25519"

Y700_DEBUG_PUBLIC_KEY_FILE="$key_dir/id_ed25519.pub" \
  bash tools/build-nixos-aarch64.sh "$PWD/result-nixos-desktop" elden-desktop

bash tools/build-nixos-rootfs.sh \
  "$PWD/result-nixos-desktop" "$PWD/artifacts/nixos-rootfs.ext4"

e2fsck -fn artifacts/nixos-rootfs.ext4
sha256sum -c artifacts/nixos-rootfs.ext4.sha256
```

The pinned `elden-desktop` configuration enables GNOME automatic login and
USB-only, key-authenticated root diagnostics. Its `y700` account has an empty
initial local password. This is a disposable development image, not a
provisioned production installation.

The rootfs builder creates a 12 GiB ext4 file and uses `sudo chown` only on
its staging directory to obtain root-owned system files. It never opens a
tablet block device and refuses an existing staging directory or image.
For later builds, choose separate `ROOTFS_STAGE`, `ROOTFS_CLOSURE` and output
paths. Never rebuild over an image currently exported to the tablet.

## Temporary Windows-hosted boot

Use Windows Python 3, Android platform-tools and an elevated PowerShell
window. Make the checkout/images readable from Windows, for example through
the Linux host's shared filesystem path. Use the actual device serial only
in the local shell and keep the log directory outside the repository.

First verify the Android model/build, battery and current slot with
serial-scoped read-only queries, then reboot the verified tablet to its
bootloader. When it is already in bootloader, run:

```powershell
.\tools\run-usb-nbd-fastboot.ps1 `
  -BootImage .\vendor\tb322fc-linux\artifacts\boot-usb-nbd.img `
  -RootfsImage .\artifacts\nixos-rootfs.ext4 `
  -FastbootSerial $DeviceSerial `
  -ExpectedSlot a `
  -LogDirectory "$env:TEMP\y700-usb-nbd-test"
```

Set `$DeviceSerial` to the verified serial before this command. Set
`-ExpectedSlot` to the current slot read from the device; this argument is a
check and does not switch slots.

The helper verifies the product, board, unlocked state, bootloader mode and
slot before issuing one `fastboot boot`. It starts a read-only NBD server,
identifies the USB gadget, and creates a scoped temporary network/firewall
configuration. No flash, erase, unlock or slot-change command is issued.

USB uses host `192.168.42.1`, tablet `192.168.42.2` and NBD port `10809`.
These are fixed development-link addresses, not a saved Wi-Fi configuration.
SSH accepts the dedicated key from the USB host address only.

Keep USB and the NBD server available until the tablet has returned to
Android and closed the connection. The helper's observation deadline does
not terminate an active NBD session. Its cleanup restores the host network
settings it changed.

## Acceptance

After boot, verify the expected system, GNOME session, active
`y700-power-key.service`, absence of failed system units and continued NBD
connectivity. Short press should toggle the display. Hold about two seconds
for the power menu, then cancel it; releasing the long hold must not also
toggle the display.

Actual system suspend remains disabled because the USB link supplies the
root disk. Display-off testing is not suspend/resume testing. An ordinary
reboot is the tested path back to Android; standalone poweroff retains the
limits recorded in [status](status.md).
