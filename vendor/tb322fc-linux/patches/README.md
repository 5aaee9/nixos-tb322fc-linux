# Local patches

Each patch applies to the corresponding public commit in `sources.json`.
`scripts/fetch-sources.py` applies the ordered `patches` list, or a legacy
single `patch`, to the Git index and verifies the exact resulting tree.

- [`kernel/`](kernel/README.md): device support and dependencies applied to
  the official Linux base, with original attribution preserved.
- `uboot/0001-physical-esp-honor-menu-timeout.patch`: removes the fixed
  15-second override from the physical-ESP provider overlay, so the installed
  systemd-boot menu configuration decides the wait. Apply to the physical-ESP
  provider packaging tree, not the embedded RAM-FAT provider in this repository.
- `hexagonrpc.patch`: writable Linux sensor registry state and safe filesystem
  descriptor/alias handling.
- `iio-sensor-proxy.patch`: SSC accelerometer discovery and claims made while
  the sensor is opening.
- `libcamera.patch`: CAMSS/simple-pipeline capture handling, sensor controls,
  request cleanup and qcam lens controls.

The patches retain the licenses of their upstream files. Downloaded source
trees stay untracked; the patch files are the maintained device changes.
