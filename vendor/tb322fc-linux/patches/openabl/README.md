# Local OpenABL build patches

Base OpenABL: `59338daddd4be82712e2e72bf15cd2f480d517b4`.
Base Qualcomm EDK2: `aef4e86045bd151a54d33bab8ae5e8e62462a8f4`, with
OpenABL's own `Abl/openabl.patch` and `Abl/QcomModulePkg` overlay applied first.
These patches are applied inside the Nix derivations in
`nix/packages/openabl.nix`. Run `nix build .#openabl` or
`nix build .#openabl-entry-probe` from the project root on x86_64 Linux.
`tools/build-openabl-sm8750.sh` is a compatibility wrapper for those packages.

1. `0001`: declare the previous settings only when standard boot is enabled.
   This fixes the `-Werror` unused-variable failure in the chain-only menu.
2. `0002`: retain escaped quotes when generating GCC-family response files
   on POSIX. Normalizing their backslashes to slashes corrupted the product
   name/version defines in long native workspace paths.
3. `0003`: compare `AvbSlotVerifyResult` with its matching OK enum. Both old
   and new OK constants equal zero, so this changes no numeric decision.
4. `0004`: return `ERROR_INVALID_ARGUMENT` for an unresolved or unknown
   hashtree error mode. Release builds omit the old assertion and could use
   uninitialized pointers on that invalid path. Valid modes are unchanged.
5. `0005`: add an opt-in `entry-probe` build mode. LinuxLoader stops before
   OpenAblMenuEarly, draws a black/green/blue/white GOP pattern with a blinking
   bottom center and waits indefinitely. No menu, settings, partition
   enumeration, Android boot or fastboot path is entered. A missing display
   is inconclusive and still cannot fall through to normal boot. This mode
   requires physical reset/recovery; it is not a functional boot menu.

The Nix builder explicitly links the ABL with GNU AArch64 BFD in non-PIE
mode. The pinned EDK2 ELF-to-PE converter expects a nonwritable text section;
LLVM LLD 21 merges the GUID data into writable text with this old linker
script, while BFD produces the expected section flags. The menu itself uses
LLVM's PE linker. The output manifest records the actual tools and inputs.
The sandbox supplies Clang, BFD, libuuid, Python dependencies and all source
inputs. No host compiler installation or Fedora container is needed.

The earlier mutable-checkout workflow used
`tools/verify-openabl-sources.py` to reconstruct the complete expected source
from each pinned Git tree plus these patches and the six upstream overlay
files. It compares file contents and modes directly, including files marked
assume-unchanged in Git. Additional staged, untracked and ignored source
files are rejected. Only exact original/generated Conf templates and the
known generated BuildEnv shell are allowed; the Prebuilt menu is bound to
this build's output. Before/configured/after source digests must agree.
Each menu compilation used a fresh object directory. This forensic verifier
remains available for historical workspaces. The Nix build instead starts
from immutable inputs checked against `flake.lock`, applies the ordered local
patches in its sandbox, and records actual revisions, NAR hashes, overlay and
patch hashes, toolchain and output hashes in `metadata.json`. Complete
byte-for-byte reproducibility, including PE and certificate timestamps, has
not been established.

The normal build does not change XBL authentication, Android key trust, slot
policy, menu settings storage, or the inherited EFI accept-all policy. The
entry probe bypasses those menu and boot paths without changing their code.
`qtestsign` still emits a dummy signature. Building this candidate does not
make it suitable for flashing on a secure-boot production device.
