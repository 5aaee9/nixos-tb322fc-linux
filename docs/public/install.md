# Complete persistent installation

`tools/install-nixos.py` coordinates a fresh NixOS GNOME installation on an
already unlocked **TB322FC / elden, SM8750, 16+512 GB** using Windows and WSL.
It allocates **256 GiB total: 1 GiB FAT32 `linux-esp` and 255 GiB ext4 `rootfs`**.
Android keeps about 193.747 GiB of raw userdata space and remains the default
boot path. This is a reset-and-recreate installation: **Android user data is
erased**, not resized in place.

The development tablet has already passed an installation and two persistent
boots using the underlying procedures. **The combined installer has offline
tests and static review only; a fresh end-to-end installation with this exact
coordinator has not been accepted on hardware.** Do not reinstall a working
tablet to use this script. Existing Linux partitions are deliberately rejected.

The installer preserves installed Android boot images, recovery, ABL and the
active slot. Its writes are the stock reset request in `misc`, the data LUN's
GPT, the stock recovery's userdata/metadata reset, and the two new Linux
filesystems. It does not install OpenABL or systemd-boot. Linux continues to
start through `fastboot boot`; the ESP is reserved for future boot integration.

## 1. Prerequisites and data backup

- Exact supported Android build:
  `TB322FC_CN_OPEN_USER_Q00041.1_W_ZUXOS_1.5.10.229_ST_260514`.
  Both recovery images must match SHA-256
  `3fc66edd5166971568811ea73221f42a3bc6637930e2a7f2c4efb2a4297585c0`.
  A different build/recovery is refused; do not edit checks to bypass this.
- Unlocking must already be complete. Start in Android with initial setup
  complete, USB debugging authorized and battery at least 50 percent.
- Back up personal Android files and app data separately. The script backs up
  GPT and selected boot/recovery/metadata partitions, **not all userdata**.
  Keep a matching stock recovery package and the means to restore it.
- Use the [Nix build guide](build.md): Nix supplies the pinned build tools and
  QEMU. The x86_64 helper needs local-store and user/mount namespace support.
  The separate installer needs Python 3.11+, OpenSSH, OpenSSL and `wslpath`.
- Windows needs Android platform-tools, Python 3 (`python.exe` or `py.exe`),
  Windows PowerShell 5.1, a working RNDIS driver and permission for an elevated
  helper. Its UAC prompt is for the USB address and scoped NBD firewall rule.
- Keep all install state on durable WSL storage outside the checkout. Allow
  at least 2 GiB for partition backups/logs and sufficient additional space for
  builds, a 12 GiB maintenance image and the rootfs archive/staging tree.
- Use one target tablet and a stable USB port. Disconnect other development
  gadgets using the same test address. Do not move the cable during a boot.
  The helpers verify the physical USB port across fastboot/RNDIS and the
  Windows route to `192.168.42.2`; unsupported topology fails before writes.

These are development images with a trusted-host USB root channel. Do not
publish private configuration, keys, backup images, logs or device identifiers.

## 2. Prepare matching sources and firmware

Follow the [private input steps](build.md#prepare-private-inputs) using this
tablet's own stock firmware. Import all 78 files against
`vendor/tb322fc-linux/firmware-tb322fc-prc.json`; the builders verify their
hashes again. Do not substitute another tablet's firmware or calibration.

Run the following commands from the repository root in WSL. Use a new output
name if any build directory/image already exists. Do not overwrite a live
NBD export.

```sh
private_dir="$HOME/y700-private"
install -d -m 700 "$private_dir"
ssh-keygen -t ed25519 -f "$private_dir/id_ed25519"
chmod 600 "$private_dir/id_ed25519"
mkdir -p "$private_dir/device-config"
python3 - "$private_dir" <<'PYKEY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
key = (p / "id_ed25519.pub").read_text().strip()
(p / "device-config/default.nix").write_text("{ debugPublicKey = " + json.dumps(key) + "; }\n")
PYKEY
```

Reuse your existing dedicated key instead of overwriting it. If it has a
passphrase, load it into `ssh-agent` with `ssh-add` before running the
installer; its SSH connections use batch mode.

## 3. Build the maintenance and installation images

The maintenance pair uses USB/NBD and includes the shutdown preparation,
filesystem tools and host SSH public key from `elden-desktop`.

```sh
nix run .#build-aarch64 -- .#rootfs-desktop \
  --override-input device-config "path:$private_dir/device-config" \
  --no-write-lock-file --out-link out/install-maintenance
nix build .#boot-usb-nbd --out-link out/install-maintenance-boot
```

Build the persistent archive from the same configuration and public key:

```sh
nix run .#build-aarch64 -- .#rootfs-archive \
  --override-input device-config "path:$private_dir/device-config" \
  --no-write-lock-file --out-link out/install-rootfs
nix build .#boot-persistent --out-link out/install-persistent-boot
```

The archive builder verifies and registers the Nix store closure and records
source pins. The persistent account starts locked, with automatic login
disabled. During installation, a private password is generated and tested
for persistence. Both boot images contain matching own-tablet firmware.

Record the local inputs for configuration:

```sh
python3 -c 'import json; print(json.load(open("out/install-maintenance/rootfs-metadata.json"))["system"])'
sha256sum out/install-maintenance-boot/boot.img \
  out/install-maintenance/nixos-rootfs.ext4 \
  out/install-persistent-boot/boot.img
cat out/install-rootfs/SHA256SUMS
```

## 4. Configure and inspect the local plan

```sh
python3 tools/install-nixos.py example \
  --output "$private_dir/install.json"
```

Edit that private JSON file. Use absolute Linux/WSL paths, including `/mnt/c`
paths for Windows executables. Keep `schema`, `android_build` and `linux_gib`
at their generated values.

| Field | Value to supply |
| --- | --- |
| `serial` | The target's actual ADB/fastboot serial, never an example serial |
| `slot` | Its current Android slot, `a` or `b`; this is checked, not changed |
| `adb`, `fastboot` | Absolute WSL paths to Windows `adb.exe` / `fastboot.exe` |
| `powershell` | The generated Windows PowerShell path, unless Windows is elsewhere |
| `ssh_private_key` | Your private host key; the corresponding public key must be in both systems |
| `maintenance_system` | `system` from `out/install-maintenance/rootfs-metadata.json` |
| `maintenance_boot` | Path and SHA-256 of `out/install-maintenance-boot/boot.img` |
| `maintenance_rootfs` | Path and SHA-256 of `out/install-maintenance/nixos-rootfs.ext4` |
| `persistent_boot` | Path and SHA-256 of `out/install-persistent-boot/boot.img` |
| `archive` | Absolute path to `out/install-rootfs/nixos-rootfs.tar.gz` |
| `archive_metadata` | Absolute path to `out/install-rootfs/metadata.json` |
| `archive_closure` | Absolute path to `out/install-rootfs/closure.txt` |

Before leaving Android, read its identity with the Windows ADB executable.
For example, set `adb_exe` and `device_serial` locally, then:

```sh
"$adb_exe" -s "$device_serial" shell getprop ro.product.model
"$adb_exe" -s "$device_serial" shell getprop ro.build.display.id
"$adb_exe" -s "$device_serial" shell getprop ro.boot.slot_suffix
"$adb_exe" -s "$device_serial" shell getprop ro.boot.flash.locked
```

The installer repeats these checks itself. The initial state must be Android,
not fastboot or an existing Linux session.

```sh
python3 tools/install-nixos.py plan \
  --config "$private_dir/install.json" \
  --output "$private_dir/install-plan.json"
```

`plan` only checks local configuration, files, checksums and source pins. It
does not contact the tablet and is not proof of device compatibility. The
exact GPT transaction is derived later from the live, backed-up device.

## 5. Start installation and allow the Android reset

Only after personal data is backed up:

```sh
python3 tools/install-nixos.py run \
  --config "$private_dir/install.json" \
  --state-dir "$private_dir/install-run" \
  --erase-android-data
```

Keep the WSL terminal, elevated helper and USB connection alive. The script:

1. Checks Android and serial-scoped fastboot identity, unlock, slot and battery,
   then performs one maintenance `fastboot boot`.
2. Verifies the maintenance system and all six UFS GPTs, unmounted state,
   recovery images, idle OTA/BCB state and filesystem tools using RAM files.
3. Saves and verifies primary/backup GPTs and the tablet's `metadata`, `misc`,
   and both copies of `boot`, `vendor_boot`, `init_boot`, `recovery` and `abl`.
   Every partition backup is checked at source, after download and at source
   again. This is a targeted recovery capsule, not a complete stock image.
4. Derives the exact 256 GiB transaction. It durably arms and reads back the
   stock factory-reset BCB request **before** shortening userdata's GPT end.
   GPT is written backup-copy first; other entries/LUNs remain unchanged.
5. Requests an ordinary reboot into the armed stock reset, then pauses.

## 6. Complete Android setup, then resume

Wait for stock recovery to finish and Android to start. Complete Android's
first-run setup, re-enable Developer options and USB debugging, and authorize
this host again. This interaction cannot be automated across a factory reset.

Run the same command with the same configuration and state directory:

```sh
python3 tools/install-nixos.py run \
  --config "$private_dir/install.json" \
  --state-dir "$private_dir/install-run"
```

The saved authorization and completed steps are reused. The script does not
repeat the reset or GPT write. It checks the smaller writable F2FS `/data`,
the original Android build/slot and the exact expected GPT before continuing:

1. Starts a new maintenance boot, validates it and preserves its SSH host keys.
2. Transfers the archive in checked chunks into RAM. It requires new Linux
   partitions without existing filesystem signatures.
3. Protects Android partition nodes, formats only `rootfs` and `linux-esp`,
   extracts with numeric ownership/permissions/ACLs/xattrs, verifies the Nix
   registration and NAR contents, and restores the SSH host identity.
4. Checks both filesystems and unchanged Android partitions/GPTs. Only after
   success does it publish the rootfs boot contract.
5. Returns to Android, performs a persistent `fastboot boot`, verifies internal
   writable ext4 with no NBD/overlay, and initializes the `y700` password.
6. Returns to Android again, boots Linux a second time and checks that the
   password and test marker survived, with GDM and required services healthy.

The generated password is in
`$private_dir/install-run/desktop-credentials.txt` (mode `0600`). It is never
printed by the script. Sign in as `y700`, change the password and reconnect
Wi-Fi. Desktop service checks do not replace seeing the screen or testing
touch, sound and the physical button.

## 7. Status, failures and later boots

```sh
python3 tools/install-nixos.py status \
  --config "$private_dir/install.json" \
  --state-dir "$private_dir/install-run"
```

The state directory contains backups, the derived GPT transaction, per-step
logs, `state.json`, private host identity and credentials. Keep it available
for recovery and never commit or publish it. The coordinator pins its source,
configuration and payload across resume.

A step marked `started` without a verified result is ambiguous. The script
refuses to repeat it; there is no `--force`. Preserve the maintenance/NBD
session and inspect the private logs and live read-only state before choosing
recovery. Do not delete state or use a new directory to bypass the stop, and
do not blindly restore GPT after Android has recreated `/data`. Backup GPT
bytes alone cannot reconstruct the erased Android data.

Normal reboot returns to Android. For later Linux boots, use the
[installed-root boot helper](persistent-rootfs.md#boot-an-approved-installation):

```powershell
.\tools\run-usb-debug-fastboot.ps1 `
  -BootImage $PersistentBootImage `
  -ExpectedBootSHA256 $PersistentBootSHA256 `
  -FastbootPath $FastbootExe `
  -FastbootSerial $DeviceSerial `
  -ExpectedSlot $CurrentSlot `
  -LogDirectory $NewPrivateLogDirectory
```

Set these variables to your recorded inputs. First verify the tablet in
Android, then use serial-scoped `adb reboot bootloader`. The helper performs
the single RAM boot and configures USB diagnostics; it never serves NBD.
After a successful internal-root boot, disconnecting USB does not remove the
root filesystem. Suspend is still disabled. Autonomous Linux startup,
OpenABL and systemd-boot generation loading remain separate work.

## Installer validation

```sh
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

On Windows, run the offline PowerShell checks:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\tests\test_usb_gadget_identity.ps1
```

Python tests simulate the coordinator and failure boundaries; PowerShell
tests parse the helpers and mock all device/network queries. Existing private
GPT snapshots also pass six-LUN read-only validation while data-LUN planning
remains strict. These checks do not execute a factory reset, partition write
or device boot. The added physical USB-port matching and the complete combined
workflow still require attended hardware acceptance before a public release.
