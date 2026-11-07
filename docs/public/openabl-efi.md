# OpenABL and board EFI candidates

The offline build now provides a complete SM8750 OpenABL candidate, a
separate board EFI kernel, two generation-specific initrds and a local FAT
ESP image containing unchanged systemd-boot. The intended route is:

```text
stock early firmware -> OpenABL
                          |-> installed Android
                          `-> EFI/BOOT/BOOTAA64.EFI (systemd-boot)
                               `-> selected kernel + initrd + DTB + NixOS system
```

The complete OpenABL/NixOS chain remains an offline development workflow. A separate
diagnostic ABL was written and read-verified on the tablet, but its boot
failed with a reported crashdump and boot loop. Original ABL restoration
and stock Android return passed on November 3, 2026, after EDL V2 cable
entry. At that stage the accepted Linux route was `fastboot boot` through
stock ABL; Linux was not booted again during that recovery. See the
[persistent-root guide](persistent-rootfs.md).

The alternative stock-ABL route has passed a bounded tablet test on
November 6, 2026:

```text
stock ABL -> fastboot boot -> kShimC -> RAM U-Boot EFI
          -> systemd-boot 260.5 -> board Linux -> RAM diagnostic userspace
```

The target supplied EFI/runtime evidence over USB, kept all UFS nodes
read-only and mounted no physical filesystem. Its timer returned to stock
Android; host cleanup passed. This is rootless boot-chain acceptance, not
full NixOS/GNOME or an installed boot menu. The normal kShimC build still
defaults to Android; the attended test used a separately verified
default-only autostart derivative.

On November 7 the same stock-ABL route also booted the installed NixOS
generation 2 through systemd-boot, with Linux 7.2.0-y700-efi and GNOME 50.5.
GDM starts on boot; a temporary RAM-only login verified the Wayland user
desktop and restored its original configuration. This follows an authorized
repair and full on-device consistency check of the Linux rootfs. The EFI
trial itself uses ro,norecovery beneath a 2 GiB RAM overlay, with all UFS
nodes read-only. The final session no longer depends on NBD. See the
[tested configuration](status.md) for the exact image and acceptance limits.
That trial used a RAM-loaded provider with embedded EFI media and did not
install a permanent menu.

The later November 7 installation converted the existing 255 GiB root to
Btrfs, preserved the original files and rollback data, and installed the
separate Android-preserving menu in `boot_a`. Normal startup now reaches
systemd-boot generation 3 and an automatically logged-in GNOME Wayland
desktop with a writable root. Original ABLs, inactive boot, ESP and GPT
hashes remain unchanged. The installed menu defaults to Linux after ten
seconds and retains Android. See [Btrfs and the installed menu](btrfs.md).

This installed route still embeds EFI files in boot.img. It does not
implement disk ESP discovery, persistent EFI variables, physical key input
in systemd-boot or independent kernel/initrd generation updates.

## Diagnostic trial and restoration

On November 2, 2026 the owner requested an empirical single-slot ABL trial
and offered physical 9008 assistance. A separate `entry-probe` candidate
has been built. It stops before the normal OpenABL menu/settings and ABL
storage paths, displays a distinctive GOP marker and waits for physical
recovery. It does not boot an operating system.

The bounded `abl_a` transaction passed on hardware after ADB-to-9008 entry:
first the original rewrite/readback, then the diagnostic candidate. Stock
`abl_b` and the captured primary GPT remained unchanged. No write command
targeted Android/Linux filesystems, GPT, misc or ESP.

After the acknowledged reset, the owner reported crashdump and boot looping;
the host initially had no matching ADB, fastboot or 9008 interface.
On November 3, the owner used an EDL V2 cable. Fresh 9008, Sahara identity
and own-device readbacks matched, and original `abl_a` was restored with
an ACK and exact full readback. `abl_b` and primary LUN4 GPT are unchanged.
Two Android checks confirmed `.229`, slot a, unlocked, and boot completed.
No other partition or active-slot command was sent during restoration.

The port-rebound recovery scripts had an incomplete manifest of actual
executed files. A post-action audit verified current file differences,
readbacks and Android return, but cannot establish retroactive pre-action
integrity. The recovery automation requires corrected manifest coverage
and review before reuse. This remains an experiment, not an OpenABL
installation procedure.

## November 4 fastboot write-policy test

At the owner's request, one independently reviewed fastboot attempt used
the same 1 MiB entry-probe image on `abl_a`. The planned successful-write
branch restored own-stock ABL in the same running fastboot session before
any reboot. No candidate boot or critical-unlock request was part of this
test.

The tablet reported `unlocked: yes`, `secure: yes` and
`Device critical unlocked: false`. Sending 1024 KB returned OKAY; Writing
returned `FAILED (remote: 'Flashing is not allowed for Critical Partitions')`.
The candidate flash was rejected, so the stock-restoration branch was not
used. One normal reboot returned to completed Android `.229`, slot a,
with matching identity/USB location and a changed boot ID.

No EDL, other partition, erase or active-slot command was sent. No readback
or OpenABL boot is claimed. This verifies the installed stock-fastboot
write-policy boundary; it does not test XBL authentication or establish a
usable OpenABL installation.

## What the upstream signed filename means

Checked on November 3, 2026: the latest official release is
[v1.2](https://github.com/OpenHandheldCollective/OpenABL/releases/tag/v1.2),
published October 24. Its `abl_signed-SM8750.elf` has SHA-256
`0dba7b90d1a36e13977c00fec87f4f5ccc8f49b98864ad495a1ed04d35e33c3a`;
the release checksum and GitHub asset digest match.

At release commit `ae7dad0eec1cbd568f270e95b6ce401527e868c9`,
[build.sh](https://github.com/OpenHandheldCollective/OpenABL/blob/ae7dad0eec1cbd568f270e95b6ce401527e868c9/build.sh#L37)
selects `-v7` for SM8750, and
[Scripts/abl.sh](https://github.com/OpenHandheldCollective/OpenABL/blob/ae7dad0eec1cbd568f270e95b6ce401527e868c9/Scripts/abl.sh#L44)
calls `qtestsign.py -v7 -o <output> abl unsigned_abl.elf`.
Current main `1a6d0c86da78380d1ab1da4a4a588421debff23d` uses the same
signing path. Both use the same pinned qtestsign revision as this project's
build: `f3df53a5f0e37ccee076541f30f9d5b8340fc2d3`.

Direct inspection of the downloaded binary confirms that the filename does
not imply an OEM signature:

| Property | Official v1.2 and failed local candidate | Own stock ABL |
| --- | --- | --- |
| Image signature | 256 bytes of `0xff`; invalid | Valid ECDSA/SHA-384 |
| Certificate root | `qtestsign Root CA - NOT SECURE` | Lenovo / Elden root |
| OEM metadata | 224 zero bytes | Nonzero |
| Root matches full target Sahara response | No | Yes |

The local build did not omit upstream's signing step. The
[pinned signer](https://github.com/msm8916-mainline/qtestsign/blob/f3df53a5f0e37ccee076541f30f9d5b8340fc2d3/mbn/hashseg.py#L326)
deliberately generates a placeholder signature, as its
[README explains](https://github.com/msm8916-mainline/qtestsign/blob/f3df53a5f0e37ccee076541f30f9d5b8340fc2d3/README.md).
Changing to this official release would retain the measured signature and
root mismatch. The release was inspected offline only.

### November 4 upstream recheck

The latest official release is still v1.2, with the same SM8750 asset digest.
Current main is now
[`2494196980170e2d57b9d2a7db30b88740643f58`](https://github.com/OpenHandheldCollective/OpenABL/tree/2494196980170e2d57b9d2a7db30b88740643f58).
Its seven commits after this project's pin reorganize settings and developer
options, including display-handoff options. The signing command and
dependency pins are unchanged. This does not establish a new authentication
route for the tablet.

The open [firmware updater PR #50](https://github.com/OpenHandheldCollective/OpenABL/pull/50)
adds an MBN compatibility check; it is not an OEM signer. We compiled its
unchanged parser at `f500aa03a40432bdfb5284d826f2dac382c3d9f5` in the
project's pinned Nix shell and ran it against the preserved images.
The official and failed candidates pass segment-digest checks but report
`signature` mismatch against stock (256-byte versus 104-byte fields).
A signature-only in-memory corruption of stock still passes that parser
and comparison, while payload corruption is rejected. These results
exercise the parser, not the full proposed updater or firmware acceptance.

The [current menu entry](https://github.com/OpenHandheldCollective/OpenABL/blob/2494196980170e2d57b9d2a7db30b88740643f58/Menu/Main.c#L1026)
requires the OpenABL MenuHost protocol and returns `EFI_NOT_FOUND` without
it. It also uses the ABL library protocol for libfdt/inflate operations.
Its DT fixup code assumes XBL already reserves the required memory.
Consequently, placing `openabl-menu.efi` on our RAM EFI filesystem is not
a complete integration. Menu/input ideas remain useful references, but
the stock-ABL/kShimC route still needs its own EFI provider and target
handoff validation.

The [current settings setup](https://github.com/OpenHandheldCollective/OpenABL/blob/2494196980170e2d57b9d2a7db30b88740643f58/Core/Settings.c#L702)
still writes a new store to the final 4 KiB of `misc` when necessary.
The normal menu therefore remains unsuitable for an unmodified no-write
trial. No new image was built or sent to the tablet during this recheck.

## Authentication and recovery limits

The pinned qtestsign source explicitly requires firmware secure boot to be
disabled. It creates an MBNv7 container with an all-`0xff` placeholder
signature, not a Lenovo/OEM firmware signature. Android bootloader unlock
does not establish that XBL will accept this replacement ABL. The stock
ABL backups have different signature/certificate structures; that comparison
alone cannot determine the tablet's fused authentication policy.

The November 2, 2026 target preflight returned `unlocked: yes`,
`secure: yes` and `Device critical unlocked: false`. It completed a normal
Android/fastboot/Android round trip on the `.229` build and retained slot a.
This is a real preflight result, not an OpenABL boot or an XBL authentication
test. No image was uploaded and no partition-write or unlock command was issued.
No supported stock fastboot route for temporarily executing this complete
ABL ELF has been established.

A subsequent bounded EDL test on November 2, 2026 accepted the same-model
`.259` QPST `xbl_s_devprg_ns.melf` on the `.229` tablet. Primary GPT regions
and both ABL readbacks matched the prior own-device backups; the normal
system reset returned to Android with unchanged build, slot and unlock
state. Only three storage reads were requested, with no partition-programming
or erase command. This demonstrates programmer acceptance and read access.
At that stage physical recovery and actual ABL rewriting were untested.
The later diagnostic trial proves original-image rewriting and candidate
writing. The November 3 restoration also establishes physical recovery
after this failed candidate and original Android return on this unit.

Further offline inspection used this tablet's actual stock ABL and UEFI,
not only reference source. The stock `secure` value comes from a TrustZone
security-state query through VerifiedBootDxe, independently of the Android
unlock flag. The earlier Sahara root-hash prefix and the full 48-byte
response captured during restoration match the stock Lenovo root; the
OpenABL test root differs. Its image signature is all FF and its OEM
metadata is zero-filled. Early firmware authentication rejection is the
leading explanation, but no crash-time firmware error or execution marker
was captured. Read-only Android access to kernel, pstore and vendor crash
logs was denied; an empty collection does not establish their absence.

A supported persistent replacement still lacks a target-proven signing
route. The entry-probe experiment failed to demonstrate execution.
The RAM EFI provider behind stock ABL supplies the working standard
EFI-chain route described above. Its acceptance does not establish
replacement-ABL authentication.

OpenABL's later EFI Security/Security2 accept-all callbacks are a separate
trust boundary. They cannot make XBL accept OpenABL itself. Android image
authentication is another separate path.

The normal OpenABL build also initializes settings in the final 4 KiB of
`misc` when no valid settings exist. Omitting `standard-boot` does not remove
this write. The entry probe bypasses this code and all normal boot paths;
the normal complete candidate still has no read-only trial mode. ABL acceptance,
reviewed recovery automation and the exact proposed ABL/ESP/settings writes
must be resolved before an installation procedure can be offered. The
successful restoration does not validate all of those remaining steps.

## Prepare the inputs

Use this tablet's own matching 78-file firmware collection, the pinned
board kernel sources, static ARM64 BusyBox and `gen_init_cpio` from the
[normal build procedure](build.md). No firmware from another device is
substituted. Build the persistent ARM64 NixOS system using the existing
stable `flake.lock`:

```sh
nix run .#build-aarch64 -- \
  .#nixosConfigurations.elden-persistent.config.system.build.toplevel \
  --out-link result-nixos-persistent \
  --override-input device-config path:/private/device-config --no-write-lock-file
nix build .#efi-lab-tools --out-link result-efi-lab-tools
```

The tested nixpkgs revision is
`da6dc0e7b26060f2f71ce3ef7088fb56ee44fa36` (NixOS 26.05). The tools include
ARM64 systemd-boot 260.5, AAVMF, QEMU, mtools and dosfstools. The assembler
also binds the loader's SHA-256; updating the lock requires reviewing and
updating that binding.

## Build a board EFI generation

Run from the repository root with a new output directory for each command:

```sh
nix build .#kernel-efi --out-link out/efi-kernel
nix run .#build-aarch64 -- .#efi-generation --out-link out/efi-generation-1 \
  --override-input device-config path:/private/device-config --no-write-lock-file
nix run .#build-aarch64 -- .#efi-esp --out-link out/efi-esp \
  --override-input device-config path:/private/device-config --no-write-lock-file
```

The EFI kernel uses the same pinned board source tree as the working
fastboot kernel but accepts an external initrd and loader command line.
It disables the forced built-in DTB, whose board patch would otherwise
discard the firmware-supplied tree. It also disables EFI pstore writes;
the existing QSEECOM machine allowlist is unchanged.

Each bundle includes the board kernel, own-tablet firmware initrd, DTB,
exact NixOS store path, generation number, board bootspec and hashes.
Its immutable ESP directory binds the generation and all three boot
payload hashes. The initrd requires exactly matching `y700.system` and
`y700.generation` arguments; choosing an old entry cannot silently follow
the current system profile. It checks the installed-root contract and
selected executable before making the root filesystem writable.

The generic `boot.json` inside the current NixOS system names a different
kernel and lacks this initrd. It is left intact. The separate board
bootspec records intended absolute `/boot/...` paths, while BLS Type 1
entries use paths relative to the ESP root.

For another generation, a consuming flake can call
`legacyPackages.<host-system>.y700.mkGeneration` with
`{ number = 2; toplevel = persistentSystem; usbDebug = false; }`, then pass
the generated derivations to `y700.mkEsp` as
`{ generations = [ generation1 generation2 ]; defaultGeneration = 2; }`.
The closure must be the matching registered ARM64 persistent system.
USB diagnostics are omitted by default. The default packages contain one
generation and do not implement deployment or garbage-collection retention.

The resulting `esp.img` is an ordinary 1 GiB host file, FAT32 with 4096-byte
sectors. All files are read back through FAT and hashed; `fsck.fat -n`
must pass. None of these scripts installs it or opens a tablet block device.

## Build OpenABL offline

The native build uses these fixed source revisions:

| Source | Revision |
| --- | --- |
| OpenHandheldCollective/OpenABL | `59338daddd4be82712e2e72bf15cd2f480d517b4` |
| CodeLinaro Qualcomm EDK2 | `aef4e86045bd151a54d33bab8ae5e8e62462a8f4` |
| rxi/microui | `0850aba860959c3e75fb3e97120ca92957f9d057` |
| msm8916-mainline/qtestsign | `f3df53a5f0e37ccee076541f30f9d5b8340fc2d3` |

Nix fetches all source revisions itself; existing mutable source checkouts
are not build inputs:

```sh
nix build .#openabl --out-link out/openabl-sm8750
nix build .#openabl-entry-probe --out-link out/openabl-entry-probe
```

The x86_64 Linux derivation declares Clang/LLVM, the AArch64 GNU linker,
Python, libuuid and all local patches. No host compiler or library path is
used. It applies the five [local patches](../../vendor/tb322fc-linux/patches/openabl/README.md)
in the build sandbox. These packages remain offline experiments; their dummy
signature does not authenticate them for this production tablet.

The selected menu features are `park-display,sysfont`. `standard-boot` is
omitted so OpenABL chains the default EFI loader instead of selecting BLS
entries itself. The ABL uses GNU BFD with `-no-pie` to satisfy this EDK2
version's ELF-to-PE converter; the menu uses LLVM's PE linker. PVMFW,
the kernel protocol and Android verified boot remain enabled.

Outputs include `openabl-menu.efi`, `abl-unsigned-sm8750.elf`,
`abl-dummy-signed-sm8750.elf`, checksums and build metadata.
The menu EFI file alone is not a complete ABL image. Neither complete ELF
file is established as acceptable to production tablet firmware.

## Offline tests and their limits

The [basic EFI lab](efi-chain-lab.md) checks AAVMF to systemd-boot to Linux.
It can also use the board EFI kernel with `--kernel out/efi-kernel`.
The fuller handoff test uses the common board init script and synthetic
root disks. Prepare both generation bundles as described above; the default
flake package alone creates generation 1:

```sh
nix build .#busybox --out-link result-busybox
nix build .#gen-init-cpio --out-link result-gen-init-cpio
nix develop --command python3 tools/test-board-efi-handoff.py \
  --kernel out/efi-kernel \
  --generation out/efi-generation-1 \
  --generation out/efi-generation-2 \
  --out out/board-efi-handoff
python3 -m unittest discover -s tests -p 'test_*.py'
```

The optional generation arguments require verified generation 1 and 2
bundles using the same kernel. They use those bundles' actual gzip initrds.
Without the arguments the harness builds smaller synthetic initrds.

On November 2, 2026, the board kernel and both real firmware initrds passed
the `2 -> 1 -> 2` one-shot cycle in one QEMU process, preserving the default
system profile. Mismatched selection, missing generation and an absent
system were rejected before root-disk writes. Synthetic Android disks and
GPT/sibling bytes stayed unchanged. The legacy fastboot handoff also passed
its five existing persistence/refusal checks after the common init change.

These tests use AAVMF, a QEMU platform DTB and synthetic stage-2 scripts.
They do not execute Qualcomm OpenABL, activate full NixOS, test the elden
DTB on hardware, or prove tablet EFI-variable persistence. A read-only
virtual ESP remaining unchanged does not establish that no write was
attempted. The two current generations share one board kernel; rollback
between distinct kernel versions remains untested.

## Updating generations later

The intended final arrangement can update kernel/initrd/DTB bundles and BLS
entries on the ESP without reflashing Android `boot.img` for each NixOS
generation. That arrangement is not installed yet.

Each selected store system and its closure must exist, be registered and
remain GC-rooted on the tablet, not just on the build host. The ESP entries
themselves are not Nix GC roots. There is currently no automatic NixOS
deployment, bootloader installation or generation-retention hook. Publication
ordering, free-space handling, retention/garbage collection and interrupted
updates still need implementation and target acceptance.

Before claiming the complete chain works, validate early ABL authentication
and recovery, both menus' display/keys, UFS and ESP reads, DT fixup,
ExitBootServices, EFI variables, two complete NixOS boots and Android return.
The existing fastboot-loaded persistent boot remains the accepted fallback.
