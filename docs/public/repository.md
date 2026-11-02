# Repository content policy

This repository stores the source needed to build and understand the NixOS
integration. It does not serve as a device backup or artifact archive.

## Included

- The pinned Nix flake and NixOS modules.
- The power-key event reader, gesture tests and desktop API adapter.
- Host-side build, firmware-import and temporary boot tooling.
- The vendored reference scripts, kernel/BusyBox configuration, source
  manifests, locally maintained kernel/userspace patches, audio
  routing/topology source and licenses.
- Firmware destination names, byte counts and SHA-256 inventories. These
  inventories contain no firmware payload or sensor calibration.
- Public instructions and a scoped hardware status record.

## Kept local

`.gitignore` excludes:

- `build/`, `out/`, `artifacts/`, Nix `result*` links, and the corresponding
  vendored build/output directories.
- `vendor/tb322fc-linux/inputs/` and `sources/`, including stock firmware,
  imported firmware and fetched upstream source checkouts.
- Raw images, firmware binaries, compiled output, private keys, environment
  files, device captures, backups and interpreter caches.
- `.agents/`, `.codex/`, `.aws/`, the workspace's `AGENTS.md`/`STATUS.md`,
  and internal documents outside `docs/public/`.
- The abandoned SN-personalization experiment. It is not part of the Linux
  build or a supported unlock procedure.

Ignoring a file does not delete it and does not remove an already tracked
copy. Before publishing, inspect the actual index:

```sh
git status --short
git diff --cached --stat
git diff --cached --check
git ls-files
```

Do not force-add a private log or generated image to bypass these rules.
New public documentation belongs in `docs/public/`. Device serial numbers,
bootloader identifiers, unique addresses, calibration and authentication
material must remain outside the published tree.
