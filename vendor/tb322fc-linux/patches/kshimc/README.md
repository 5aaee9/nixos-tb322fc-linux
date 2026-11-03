# TB322FC diagnostic patch

The runtime and all dependencies are pinned in `sources.json` and `flake.lock`.
The base is tc1911/kShimC4sheng at
`51aef95e6bb5fa569c4653e96f3f06ca02f9d784`; upstream authorship is retained.

`0001` adds an opt-in 20-second menu deadline and a DT diagnostic marker,
fixes disabled-charger compilation and LVGL path macro expansion, and allows
CrDK preparation from a verified immutable archive in the Nix sandbox.
The default runtime behavior is unchanged when the deadline is zero.

The TB322FC config disables PMIC settings persistence, charger takeover,
advanced/power/UEFI actions, touch, SMP and debug UART. The runtime is 4 MiB.
The packed diagnostic contains the original Android kernel as its only boot
entry. It is an offline candidate; no target-device execution is implied.

The dedicated host test runs the actual GUI, serial and settings loops with
scripted time/input. Only that fixture advances fake time during framebuffer
polling, including the final busy-loop boot hint. Production timer behavior
is unchanged. The Nix image depends on this ASan/UBSan test.

Build with `nix build .#boot-kshimc` after importing the verified own-tablet
stock boot. `nix/packages/kshimc.nix` validates the patch hash, generated
configuration, undefined symbols and runtime size. The separate image verifier
checks the ARM64 entry continuation, manifest bounds and exact stock-kernel
restoration. A software deadline is not a hardware watchdog.
