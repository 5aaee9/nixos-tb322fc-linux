# Tested configuration and limits

## November 7, 2026 installed Btrfs desktop

The existing 255 GiB Linux rootfs was converted to Btrfs after a clean ext4
check and complete private backup. All 171,510 original regular-file hashes
match after conversion. The label, UUID and partition geometry are retained,
and `ext2_saved` remains available. On-device read-only Btrfs checks report
no errors, with conversion-layout alignment warnings preserved in the logs.
No balance, defragmentation or rollback-subvolume deletion was performed.

One Android-preserving menu image was written to `boot_a` and read back in
full. Its SHA-256 is
`920f6a576a21476a79681c175dbd46e1505cb49d7ace1efe0f9b855d4d4287bf`.
A normal installed boot now passes:

```text
stock ABL -> installed kShimC -> RAM U-Boot EFI -> systemd-boot 260.5
          -> Linux 7.2.0-y700-efi -> NixOS generation 3 -> GNOME 50.5
```

The root mount is Btrfs, writable, with `noatime,compress=zstd:1`. It has no
RAM overlay or NBD dependency. GDM automatically opens an active `y700`
Wayland session. All five Btrfs device-error counters and the failed system
service count are zero. Complete protected-image hashes and all twelve GPT
edge hashes match the pre-install records; original ABLs, inactive boot,
init_boot/vendor_boot/dtbo, ESP and slot a are retained.

The menu defaults to Linux after ten seconds and retains the exact original
Android kernel and selectable Android entry. This installed-image test
validates Linux startup; it has not repeated an Android round trip or
physical screen/audio acceptance. The EFI UCM fallback is included, but
Wi-Fi association and physical speaker output remain subject to the
peripheral limitations recorded below. Suspend remains disabled.

EFI media is still embedded in the boot image. Independent generation
deployment to the disk ESP and physical key input in systemd-boot are not
implemented. See [Btrfs and installed menu](btrfs.md) for build and migration
boundaries. The following RAM trials are historical evidence.

## Earlier November 7, 2026 RAM UEFI NixOS desktop

The earlier RAM trial booted through stock ABL, kShimC, RAM U-Boot EFI and
systemd-boot 260.5 into the installed NixOS generation 2. The kernel is
Linux 7.2.0-y700-efi. GDM starts successfully; an active GNOME 50.5 Wayland
desktop was verified after a temporary RAM-only login. Its original login
configuration was restored. No system service is failed.

The previously dirty Linux rootfs was repaired with the owner's permission
in the known RAM/NBD maintenance environment and passed a full on-device
read-only consistency check. The subsequent EFI trial keeps all 120 UFS
nodes read-only and mounts that healthy root ro,norecovery beneath a 2 GiB
RAM overlay. The final session does not depend on NBD.

The tested UEFI-autostart image SHA-256 is
`0db8cc5bb62afa7545df802162be677265f13b38e96e2679ba8a1c8d17a9d9da`.
It is still loaded with `fastboot boot`. Stock ABL, Android, slot a and
installed boot images are retained. Physical desktop/touch confirmation
of this EFI session, permanent menu installation and generation deployment
to ESP remain separate acceptance items. This does not validate OpenABL.

The owner's subsequent peripheral report exposes an EFI-specific UCM
selection failure: SMBIOS changes the sound-card long name. A new
board-name-guarded driver fallback restores the existing HiFi/Speaker route
in RAM, and real stereo PCM plus a bounded test-tone playback pass.
Physical sound confirmation and deployment of the new UCM package remain
pending. The current image itself still contains the old UCM.

Wi-Fi enumerates and scans both bands with the matching own-device
firmware, but the selected WPA3 access point rejects SAE confirmation.
A live SAE-only comparison reproduces the rejection without FT roaming.
This session has no successful association/DHCP acceptance; credential
re-entry or AP-side evidence is needed before assigning a root cause.

## November 6, 2026 RAM UEFI chain

One independently reviewed `fastboot boot` now passes the actual tablet
chain: stock ABL -> kShimC -> RAM U-Boot EFI -> systemd-boot 260.5 ->
Linux 7.2.0-y700-efi -> rootless diagnostic userspace. USB evidence records
the provider and selected `y700-efi-diag.conf` entry. The tested image
SHA-256 is `a247d1fe379d33edfbaec6fadcf8c395d8650e9abfeb5beaac2c46d5e776d459`.

All 120 UFS nodes were read-only and no physical filesystem was mounted.
The diagnostic automatically returned to retained Android .229 on slot a;
host network cleanup passed. This validates the EFI/Linux diagnostic
chain. At that stage, full NixOS/GNOME, installed-generation selection and
persistent EFI variables were unvalidated through this provider.

The subsequent readonly rootfs inspection finds pending journal recovery
and orphan flags. Prior directory checksum errors remain unresolved, so
the conditional full NixOS/GNOME trial stops before mounting or booting.
No filesystem repair or write follows that inspection.

Separately, an offline correction to the readonly init's RAM fstab and
early devtmpfs aliases passes a control/corrected QEMU comparison with
the actual NixOS stage2, activation and systemd. The remount service
succeeds and all six synthetic disks remain byte-identical. The resulting
v4 EFI image was built but untested at that point. The separately authorized
November 7 repair and target trial above subsequently cleared those gates.

## Display-off limitation

Display blanking in the previously tested kernel can leave the AW99706
backlight enabled: its update callback used the saved brightness without
honoring the backlight core power/blanking state. A disabled DRM connector
or `bl_power=4` alone did not establish physical backlight-off.

The separate local patch
`0002-backlight-aw99706-honor-blanking.patch` uses effective brightness.
The actual callbacks pass 12 simulated register-state checks, and Nix
verifies the patched source tree and compiles the ARM64 driver. That tree
now boots in the rootless EFI diagnostic, but the display-off behavior has
not been tested on the tablet. Physical darkness and restored display
and touch remain required; real suspend is still disabled.

## November 3, 2026 Nix build migration

Artifact construction now uses `flake-parts`, the existing pinned stable
nixpkgs, local board patches and fixed-hash own-device firmware inputs.
The x86_64 host has built the three board kernel variants, USB/NBD and
persistent Android boot images, GNOME rootfs, board EFI generation/ESP,
kShimC Android-base diagnostic and both OpenABL experiments inside Nix.
Flake evaluation also passes for the aarch64-linux host outputs; this does
not mean every package was rebuilt on a native ARM64 host.

The final Nix tools also pass the two basic QEMU EFI selections, five
persistent-root scenarios and the board EFI kernel's `2 -> 1 -> 2` cycle
with three rejection cases. These use synthetic stage2 and simulated disks,
not a tablet boot or full NixOS activation.

The builds check source-tree identities, image formats, firmware hashes,
rootfs registration/permissions, EFI readback and kShimC negative cases.
See the [Nix build guide](build.md) for the artifact interface. The Nix-built
Linux images have no new tablet boot acceptance. Default configuration supplies no
SSH key; persistent login starts locked. Use an intended public-only device
configuration for a separately reviewed hardware test.

## November 3, 2026 kShimC RAM diagnostic

Two separately authorized and independently reviewed trials sent the same
Nix-built Android-only diagnostic using `fastboot boot` behind the original
ABL. Transfer and Booting returned OKAY; retained Android `.229` returned
with boot completion, changed boot IDs, slot a and the same physical USB
port. No flash, erase, unlock, slot change or partition installation was
performed. The owner requested the second run for observation and confirmed
normal kShimC startup with Android displayed.

The expected DT diagnostic marker is absent. A later read-only check reports
boot reason `bootloader`, but raw FDT and crash/kernel logs are unavailable
to the Android shell. Physical observation now establishes a visible kShimC
screen; rotation, keys and the exact low-level handoff remain unverified.
Source review found an FDT cache-clean coverage gap, but it is not yet a
confirmed cause of the missing marker. There is no UEFI or Linux payload in
this candidate and no systemd-boot acceptance from these trials.

## Prior hardware evidence

The November 2, 2026 persistent-root tests passed installation, two internal
ext4 boots and a return to retained Android, with 1 GiB ESP + 255 GiB rootfs.
The same board boot image loads a compatible second userspace generation;
password and test-file persistence pass. The owner confirms physical
power-key behavior. Suspend remains disabled and standalone poweroff remains
unverified. See the [persistent-root guide](persistent-rootfs.md) and
[complete installation workflow](install.md). The new combined installer
has offline tests only; it has not repeated the destructive installation.

The separate [OpenABL / board EFI workflow](openabl-efi.md) now produces a
complete native SM8750 candidate and an ESP with board kernel/initrd/DTB
bundles. QEMU passed a systemd-boot `2 -> 1 -> 2` one-shot cycle using the
actual firmware initrds, plus pre-write refusal checks. The emulator uses
AAVMF and synthetic stage 2, not Qualcomm OpenABL or full NixOS.

A later real-device preflight completed an Android/fastboot/Android round
trip. The target reports `unlocked: yes`, `secure: yes` and
`Device critical unlocked: false`; Android `.229` and slot a were confirmed
after returning. No candidate was uploaded or executed and no partition
write or unlock command was issued during that preflight. At that stage,
candidate acceptance, independent recovery and automatic misc writes
remained unresolved.

The subsequent November 2 recovery-read test passed one Android/9008/Android
round trip. A same-model `.259` QPST programmer was accepted on this `.229`
tablet; primary GPT regions and both stock ABL readbacks matched the existing
backups. No partition-programming, erase or slot-change command was sent.
Programmer acceptance and bounded reads are now proven on this target.
Physical entry after ABL failure, actual write restoration and OpenABL
authentication were still separate, untested requirements at that stage.

Offline inspection of the actual stock ABL/UEFI subsequently traced
`secure: yes` to the firmware's TrustZone security-state query, separately
from Android unlock. The OpenABL candidate has a different test root,
an all-FF signature and zero-filled OEM metadata; it does not satisfy
ordinary stock OEM authentication. This offline analysis alone did not
measure hardware rejection.
The owner subsequently authorized a single-slot empirical trial and offered
physical 9008 assistance. A separate entry-probe image is built; it stops
before menu/settings and normal ABL storage handling. The fixed `abl_a`
writer and original-image restore pass offline tests and independent review.
The ADB-to-9008 hardware trial then rewrote/read-verified original `abl_a`
and installed/read-verified the candidate; stock `abl_b` and primary GPT
stayed unchanged. The owner reported crashdump and boot looping after reset.

On November 3, 2026, the owner used an EDL V2 cable and fresh 9008 observations
and Sahara/own-device readbacks matched. One original-`abl_a` restoration,
exact readback and normal reset passed. `abl_b` and primary LUN4 GPT are
unchanged; two checks confirm stock Android `.229`, slot a, unlocked and
boot completed. Linux was not revalidated during restoration. The relocated
recovery's file-freeze coverage was incomplete; a post-action audit supports
the results but does not supply retroactive pre-action integrity.

The official OpenABL v1.2 `abl_signed-SM8750.elf` was then downloaded and
checked against its checksum and GitHub digest. It uses the same qtestsign
v7 path, all-FF signature, test root and zero OEM metadata as the failed
candidate. The complete 48-byte Sahara root response matches both stock
roots and differs from both OpenABL images. Firmware authentication is the
leading failure explanation, with no captured crash-time firmware error.
See the [source and signing comparison](openabl-efi.md#what-the-upstream-signed-filename-means).
There is no working OpenABL installation.
A RAM EFI provider behind stock ABL subsequently passed the November 6
rootless diagnostic described at the top of this page.

On November 4, one separately reviewed fastboot `abl_a` candidate request
transferred 1024 KB but was rejected with
`Flashing is not allowed for Critical Partitions`. Fresh critical-unlock
state remained false. No stock-restoration flash was needed; one normal
reboot returned to completed Android `.229`, slot a, with the same physical
USB identity and a changed boot ID. No EDL, critical unlock, erase, slot
change or other partition command was issued. This is a rejected write,
not an OpenABL boot or XBL authentication test.

The dated record below describes the earlier USB/NBD system tested on
November 1, 2026. It is separate from the vendored reference project's
hardware matrix and `validation.json`.

## Inputs

- Hardware: TB322FC / elden, SM8750, 16 GB RAM and 512 GB storage.
- Tested kernel tree: `abb1b30a2ef5c0a7fc5e3e4ed35bbefb02462da4`, originally
  supplied by `GEEKiDoS/linux@b0c05eb72e10140f87efd0e499ad840e6c3e6975`.
- Current source packaging: official Linux
  `8d3ae59288f1e7d58d76558a6ee96d533bc5019f` plus the
  [local kernel patches](../../vendor/tb322fc-linux/patches/kernel/README.md).
  The first patch reproduces the tested kernel tree. With the display-off
  fix, the current tree is `28aac546fa1a11a7ed0847f1680ac1fec0100c6d`,
  which subsequently booted through EFI; physical display-off acceptance
  remains pending.
- Nixpkgs: `da6dc0e7b26060f2f71ce3ef7088fb56ee44fa36`.
- Firmware inventory: `vendor/tb322fc-linux/firmware-tb322fc-prc.json`,
  78 files checked against the matching stock inputs.
- Root delivery: read-only USB/NBD with a 2 GiB tmpfs overlay.

The local tested boot image had SHA-256
`de59857dbb9a6d8cb8fa9ba354f5717200cee2be289f17a51b8901ad776aad00`.
The local tested 12 GiB power-key rootfs had SHA-256
`b8654f022a4d036ba8826a947b9aa84ca91495683dfcb9a231a0caffef596249`.
These identify the tests; the binaries are not published in Git. Another
developer's SSH key or filesystem build metadata will change image hashes.

## Target evidence

| Area | Result and boundary |
| --- | --- |
| Boot | Serial-scoped `fastboot boot` reaches the expected NixOS system. No Linux partition write or slot change is part of this test path. |
| GNOME | GDM automatically enters an active Wayland desktop. |
| Display | Native DSI panel/backlight active; connector/core blanking cycles pass. AW99706 can retain its light output during blanking; the separate fix has offline tests only. Physical backlight-off and recovery are not yet accepted. |
| Touch | Owner confirmed touch on an earlier desktop image; touch firmware reload is observed after display cycling. Full gesture/resume acceptance is not claimed. |
| GPU | GNOME uses MSM/GBM/EGL and measured GPU execution increases. Conformance and sustained workloads are not validated. |
| Wi-Fi | Owner joined a network and authenticated SSH succeeded on an earlier image. The fresh disposable overlay has no saved Wi-Fi credentials. |
| Speakers | Exact-board UCM routing and bounded playback passed; the owner confirmed normal sound. Microphones/headset routing are not accepted. |
| Power key | Fresh boot activates the udev/systemd handler without manual installation. Short 150 ms and 1.4 s holds toggle the display; a long hold dispatches the menu at about 2.003 s. Cancellation and subsequent short presses pass. Physical button acceptance remains pending. |
| Firewall | Repaired kernel provides the required built-in filtering support; USB SSH and NBD work with the rules enabled. |
| Shutdown | Ordinary reboots returned to the retained Android installation. Standalone poweroff and the final shutdown console trace are not validated. |
| Suspend | Deliberately disabled for USB/NBD. Display-off is not suspend, and no genuine suspend/resume success is claimed. |
| Storage | No persistent Linux installation. Android uses encrypted F2FS; no safe shrink procedure is established. |
| Other hardware | Bluetooth, cameras, sensors, charging behavior, external display and long-duration performance are not accepted for this NixOS image. |

## Power-key design

Udev identifies the dedicated `pmic_pwrkey` input device. A systemd service
verifies that it exposes only `KEY_POWER`, takes an exclusive evdev grab and
waits on input, a monotonic timer and signals. There is no periodic polling.

Short release toggles Mutter display power; a two-second hold sends a request
for GNOME's existing power menu. A separate adapter resolves the active
session and drops to the development user before calling its session bus.
A locked session can be lit but is not unlocked by the handler.

GNOME's power binding is empty and logind ignores both power-key actions.
The original GNOME binaries and unrelated media-key behavior are retained.
The service is limited to the `root=usb-nbd` development boot.

Unit tests cover the threshold, duplicate/repeated input, release after hold,
a held key at startup and dropped-event reset. On-device injected-event tests
also verified a stopped-handler control and recovery after restart, with
unchanged boot identity/NBD client and zero suspend counts. These tests do
not replace a real button/panel check.
