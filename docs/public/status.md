# Tested configuration and limits

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
There is no working OpenABL installation or new candidate flash.
A RAM EFI provider behind stock ABL remains an alternate investigation and
is not yet a tested tablet boot path.

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
  The resulting tree is identical to the tested kernel tree. This packaging
  check does not claim a new image build or device test.
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
| Display | Native DSI panel/backlight active; display-only off/on cycles pass machine checks. Physical panel observation after the final power-key change remains pending. |
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
