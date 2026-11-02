# Tested configuration and limits

This record describes the TB322FC/elden NixOS development system tested on
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
