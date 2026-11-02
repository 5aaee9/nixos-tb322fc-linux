# Contributing

Report the device model, kernel commit, boot-image SHA256, rootfs distribution,
steps to reproduce and relevant logs. Remove personal device identifiers and
network credentials before posting logs.

Kernel changes belong in the linked kernel repository. Update its source pin
only after a built-in configuration is tested on the tablet. General fixes
should remain general; use devicetree for hardware distinctions. Battery and
charging changes need separate tests and commits.

For userspace changes, update the bundled patch and expected tree in
`sources.json`, then verify a fresh fetch. Preserve upstream source attribution
and licensing. Do not add private binary payloads, unresolvable submodules,
experiment labels, calibration from one device or links to local workspaces.

Run `python3 scripts/check.py` before committing. Build/boot changes also need
an actual image build and device test. Boot only with `fastboot boot`; keep
fallback artifacts and calibration outside the public repository. Do not
flash partitions or blindly retry a failed controller path.
