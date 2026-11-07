# TB322FC RAM diagnostic patches

The runtime and all dependencies are pinned in `sources.json` and `flake.lock`.
The base is tc1911/kShimC4sheng at
`51aef95e6bb5fa569c4653e96f3f06ca02f9d784`; upstream authorship is retained.

`0001` adds an opt-in 20-second menu deadline and a DT diagnostic marker,
fixes disabled-charger compilation and LVGL path macro expansion, and allows
CrDK preparation from a verified immutable archive in the Nix sandbox.
The default runtime behavior is unchanged when the deadline is zero.

`0002` includes the incoming writable FDT in early-MMU handoff cache cleaning.
Its host test executes the real configuration/handoff path and checks that
both the original FDT and runtime are cleaned, without sweeping all RAM.

`0003` checks the narrow no-copy Linux entry's actual physical alignment,
file/BSS extent, runtime and original-FDT separation, declared RAM and
firmware reservations before jumping. Rejection selects the retained Android
entry and adds the rejection code to the diagnostic marker. This happens
after ABL has loaded the combined image; it cannot validate ABL's initial
placement or establish its acceptance of an oversized RAM download.

`0004` adds a separate four-entry RAM UEFI contract. It validates the provider's
ARM64 image/BSS and elden DT template, keeps the original Android fallback DT,
and passes the complete packed-image range to the provider. It rejects
unavailable incoming reserved-memory nodes with a concrete `reg`, because
the upstream capture path would otherwise omit those ranges. The existing
three-entry direct Linux guard remains separate.

The TB322FC config disables PMIC settings persistence, charger takeover,
advanced/power/UEFI actions, touch, SMP and debug UART. The runtime is 4 MiB.
`boot-kshimc` contains only the original Android kernel. The separate
`boot-kshimc-linux-ram` adds a Linux entry with a built-in elden DT/initramfs
and an internal root mounted read-only beneath a 2 GiB RAM overlay. Android
remains the default in both. Neither package installs itself on the tablet.
These updated patches require their own target validation.

`boot-kshimc-uefi-ram` adds the isolated RAM UEFI provider and its DT instead
of the direct Linux payload. Its first target initrd is a rootless EFI-chain
diagnostic. It is not an installed NixOS generation selector. The provider
source, limitations and build instructions are in `../../uefi/README.md`.

The dedicated host test runs the actual GUI, serial and settings loops with
scripted time/input. Only that fixture advances fake time during framebuffer
polling, including the final busy-loop boot hint. Production timer behavior
is unchanged. The Nix image depends on this ASan/UBSan test.

Build with `nix build .#boot-kshimc` after importing the verified own-tablet
stock boot. `nix/packages/kshimc.nix` validates the patch hash, generated
configuration, undefined symbols and runtime size. The separate image verifier
checks the ARM64 entry continuation, manifest bounds and exact stock-kernel
restoration. A software deadline is not a hardware watchdog.
