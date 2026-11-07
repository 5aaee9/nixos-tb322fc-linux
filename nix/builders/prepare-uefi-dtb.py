"""Prepare the exact board DT template for the first rootless EFI experiment."""
from pathlib import Path
import shutil
import subprocess
import sys

source, output = map(Path, sys.argv[1:3])
shutil.copyfile(source, output)
output.chmod(0o644)


def put(kind, node, name, *values):
    subprocess.run(["fdtput", "-t", kind, str(output), node, name, *values], check=True)


# kShimC replaces the disabled template with measured scanout metadata.
put("s", "/chosen/framebuffer@fc800000", "status", "disabled")
put("s", "/chosen", "y700,ram-uefi-template", "v1")
put("s", "/chosen", "y700,uefi-provider", "unused")
# The first experiment is rootless and does not use audio/FastRPC. Defer this
# dynamically allocated OS heap; do not invent a firmware reservation for it.
put("s", "/reserved-memory/adsp-rpc-remote-heap", "status", "disabled")
