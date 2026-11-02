# Userspace patches

Each patch applies to the corresponding public commit in `sources.json`.
`scripts/fetch-sources.py` applies it to the Git index and verifies the exact
resulting tree. This avoids relying on unpublished branches or private builds.

- `hexagonrpc.patch`: writable Linux sensor registry state and safe filesystem
  descriptor/alias handling.
- `iio-sensor-proxy.patch`: SSC accelerometer discovery and claims made while
  the sensor is opening.
- `libcamera.patch`: CAMSS/simple-pipeline capture handling, sensor controls,
  request cleanup and qcam lens controls.

The patches retain the licenses of their upstream files. Kernel changes are
already published in the pinned kernel repository and are not duplicated here.
