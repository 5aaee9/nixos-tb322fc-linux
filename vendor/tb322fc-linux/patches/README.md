# Local patches

Each patch applies to the corresponding public commit in `sources.json`.
`scripts/fetch-sources.py` applies the ordered `patches` list, or a legacy
single `patch`, to the Git index and verifies the exact resulting tree.

- [`kernel/`](kernel/README.md): device support and dependencies applied to
  the official Linux base, with original attribution preserved.
- `hexagonrpc.patch`: writable Linux sensor registry state and safe filesystem
  descriptor/alias handling.
- `iio-sensor-proxy.patch`: SSC accelerometer discovery and claims made while
  the sensor is opening.
- `libcamera.patch`: CAMSS/simple-pipeline capture handling, sensor controls,
  request cleanup and qcam lens controls.

The patches retain the licenses of their upstream files. Downloaded source
trees stay untracked; the patch files are the maintained device changes.
