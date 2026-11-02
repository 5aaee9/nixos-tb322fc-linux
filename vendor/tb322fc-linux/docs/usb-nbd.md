# Temporary USB/NBD rootfs delivery

`boot-usb-nbd.img` is a development-only image for the TB322FC/elden. It
keeps Android in place and expects the host to provide the NixOS image over a
USB RNDIS network link:

1. The initramfs creates a single RNDIS gadget and assigns the tablet
   `192.168.42.2/24`.
2. The Windows host assigns `192.168.42.1/24` to the new RNDIS adapter.
3. The host serves `artifacts/nixos-rootfs.ext4` on TCP port `10809` using the
   small Python NBD server in `tools/serve-rootfs-nbd.py`.
4. The tablet connects with BusyBox `nbd-client`, mounts the image read-only,
   and places a 2 GiB tmpfs overlay above it.
5. The initramfs switches into that temporary overlay and starts NixOS.

The canonical ext4 image is opened read-only by default. The overlay is lost
when the tablet reboots, so NixOS state created during this test does not
modify Android or the host image.

## Build

From the project root:

```sh
vendor/tb322fc-linux/scripts/build-boot-usb-nbd.sh
(cd vendor/tb322fc-linux/artifacts && sha256sum -c USB-NBD-SHA256SUMS)
```

The script uses an isolated kernel output directory and writes
`vendor/tb322fc-linux/artifacts/boot-usb-nbd.img`; it does not replace the
previously verified `artifacts/boot.img`.

The USB variant keeps the DWC3 dual-role path
(`CONFIG_USB_DWC3_DUAL_ROLE`), enables `CONFIG_USB_CONFIGFS_RNDIS` and
`CONFIG_BLK_DEV_NBD` as built-in kernel features, and uses the gadget side of
the dual-role controller. Its command line uses `root=usb-nbd` and
`fstab=no`; the custom initramfs performs the actual NBD and overlay handoff.

## Windows test

The tablet must be connected with USB debugging and an unlocked bootloader.
Open an elevated PowerShell window at the repository's Windows path and run:

```powershell
.\tools\run-usb-nbd-fastboot.ps1 `
  -BootImage .\vendor\tb322fc-linux\artifacts\boot-usb-nbd.img `
  -RootfsImage .\artifacts\nixos-rootfs.ext4 `
  -FastbootSerial <serial> `
  -LogDirectory "$env:TEMP\y700-usb-nbd-test"
```

The helper starts the read-only NBD server before invoking exactly one
bootloader operation:

```text
fastboot -s <serial> boot <image>
```

The serial is mandatory. Before sending the image, the helper checks the
TB322FC product/board identity, unlocked state, bootloader mode, and expected
active slot. It records raw results in the private log directory. It waits
for the expected gadget MAC and USB VID/PID, assigns the temporary host
address, and keeps the server alive while the tablet boots.

After the bootloader accepts the image, the helper adds a temporary inbound
Windows Firewall rule for TCP port `10809`, restricted to the gadget adapter,
host test address and tablet address. The server also rejects other client
addresses. The helper removes its added address and rule and restores the
adapter's previous DHCP setting during cleanup. It refuses to reuse an
existing host test address or occupied server port.

The helper never calls `fastboot flash`, `fastboot erase`, `set_active`, or
any partition-writing command. The observation deadline does not stop an
active NBD session. Reboot the tablet to Android and wait for its NBD
connection to close before stopping the host helper; stopping the export
while Linux is using it disconnects its root filesystem. Cleanup removes
the temporary `192.168.42.1` address. The helper requires Windows Python 3
and prefers the interpreter directly over the optional `py.exe` launcher.

The initramfs requests a reboot after an explicit handoff failure and the
kernel uses `panic=30`. A hard lock or stage2 hang can still require the
hardware power key. Keep the first test attended.

The target bootloader must permit `fastboot boot`. If ABL returns
`Fastboot boot command is not available in locked device`, record the result
and stop. Do not use `fastboot flashing unlock` under the no-write procedure:
an OEM unlock may erase user data and requires a separate user decision.

On the attached TB322FC, an AVB-signed candidate was also transferred once.
The candidate used the AOSP Testing key and the `boot_a` partition size, but the
locked ABL returned the same error before Linux started. Therefore signing
does not make this device's `fastboot boot` command available while the
bootloader remains locked. See [AVB signing](avb.md) for the exact parameters
and evidence.

## Evidence

Record the image hash, kernel configuration, host adapter name, the NBD server
connection line, and the tablet's serial console or display result. A
successful `fastboot boot` transfer only proves that ABL accepted the image;
it does not prove that the kernel, USB gadget, NBD handoff, display, touch,
GPU, Wi-Fi, or GNOME reached a usable state.
