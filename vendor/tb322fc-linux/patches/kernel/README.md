# Maintained kernel patches

Kernel builds fetch the official Linux repository and apply the ordered
`kernel.patches` list in `../../sources.json`. The third-party device fork is
not a build input. Linux source remains an external, pinned upstream input;
downloaded checkouts are not committed to this repository.

## Baseline and provenance

- Upstream: official Linux 7.2, commit
  `8d3ae59288f1e7d58d76558a6ee96d533bc5019f`.
- Upstream source tree: `a25d6a94ad99aa059aa6dc728c45052fb2968352`.
- Initial board source tree: `abb1b30a2ef5c0a7fc5e3e4ed35bbefb02462da4`.
- Current patched source tree: `28aac546fa1a11a7ed0847f1680ac1fec0100c6d`.
- Initial patch:
  [`0001-y700-gen4-support.patch`](0001-y700-gen4-support.patch).
- Original device commit:
  `GEEKiDoS/linux@b0c05eb72e10140f87efd0e499ad840e6c3e6975`.

The initial patch is a complete export of the device commit against its
upstream parent. It retains the original author, date, message, sign-off,
source attribution and license notices, including Pengyu Luo's work.
It changes 150 text files across the board description and its dependencies.
Its historical validation claims describe the original reference system;
current NixOS acceptance is recorded separately in
[the target status](../../../../docs/public/status.md).

This import keeps the complete tested board and driver dependencies together.
It does not change kernel behavior or add firmware/calibration payloads.
Reproducing the exact source tree is the acceptance criterion for this
packaging change. It does not promise byte-identical images across different
toolchains, build metadata or Git histories.

## Display blanking fix

`0002-backlight-aw99706-honor-blanking.patch` changes the AW99706
`update_status` callback to use `backlight_get_brightness()`. The previous
callback ignored power/blanking/suspend state and continued applying the
saved nonzero brightness after the panel requested backlight-off.
The helper supplies zero while blanked, allowing the existing hardware path
to clear the brightness registers and backlight enable bit. Unblanking
restores the saved requested brightness.

This does not enable system suspend, change GNOME policy or claim that all
display power rails are off. Target backlight-off and display/touch recovery
must be validated on a separately built image before marking the fix
accepted.

## Making a change

1. Use a separate development checkout of the pinned official base. Apply
   this directory's patches in manifest order, using `git am` to preserve
   their authors when preparing additional commits.
2. Make one focused commit per hardware fix. Preserve attribution and avoid
   unrelated cleanup in the imported baseline.
3. Export each new commit with `git format-patch --full-index --binary`.
   Add its numbered patch path to `kernel.patches` in `sources.json`.
4. Update `kernel.tree` to the final `git write-tree` value. When changing the
   upstream base, update `kernel.commit` and `kernel.base_tree` as well.
5. Verify a fresh fetch, build a separate image and complete the appropriate
   RAM-only `fastboot boot` regressions before marking changed behavior tested.

The production fetcher uses `git apply --index` and leaves HEAD at the pinned
upstream commit. Staged changes in that generated checkout are expected.
The build scripts verify its full index tree and reject unstaged changes.
Existing source directories are never reset automatically.

When upstream provides equivalent support, remove the corresponding local
patch after checking the resulting source and target behavior. The initial
aggregate patch may need to be split by subsystem during that rebase.

Run the repository checks from `vendor/tb322fc-linux`:

```sh
python3 scripts/check.py
python3 scripts/test-fetch-sources.py
```
