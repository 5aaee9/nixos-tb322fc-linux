# Pinned reference inputs

This directory contains the direct Y700 Gen 4 reference integration snapshot,
with local USB/NBD, firmware-manifest and firewall build adaptations.

- `tb322fc-linux`: `473f3e075cf328e094db3e79721fefeed248d42b`
- kernel input: `GEEKiDoS/linux@b0c05eb72e10140f87efd0e499ad840e6c3e6975`

The vendored license and component notices are retained. Downloaded sources,
firmware and build artifacts are excluded from Git. The original hardware
matrix and validation record belong to the reference system; current NixOS
results are recorded in [public status](../docs/public/status.md).

Do not copy board-specific DTS values, firmware, calibration or partition
values from another tablet into this project.
