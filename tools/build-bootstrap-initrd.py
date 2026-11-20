#!/usr/bin/env python3
"""Package the immutable storage reader and its Nix-owned userspace tools."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess


def adsp_firmware(directory, manifest):
    """PMIC GLINK needs ADSP before the bootstrap can expose USB diagnostics."""
    selected = {}
    for entry in json.loads(manifest.read_text())["files"]:
        name = entry["path"]
        if not re.fullmatch(r"qcom/sm8750/adsp(?:_dtb)?\.(?:mdt|b[0-9]{2})", name):
            continue
        source = directory / name
        if name in selected or source.is_symlink() or not source.is_file():
            raise ValueError("Invalid bootstrap firmware file: " + name)
        data = source.read_bytes()
        if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("Bootstrap firmware differs from the captured manifest: " + name)
        selected[name] = source
    for prefix in ("qcom/sm8750/adsp", "qcom/sm8750/adsp_dtb"):
        if prefix + ".mdt" not in selected or prefix + ".b00" not in selected:
            raise ValueError("Missing bootstrap firmware family: " + prefix)
    return selected


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("closure", "busybox", "kexec", "dtc", "provider", "init", "usb",
                 "cpio", "firmware", "firmware-manifest", "out"):
        p.add_argument("--" + name, required=True, type=Path)
    a = p.parse_args()
    firmware = adsp_firmware(a.firmware, a.firmware_manifest)
    a.out.mkdir()
    records = {}

    def directory(path):
        if path == "/":
            return
        directory(str(Path(path).parent))
        records.setdefault(path, f"dir {path} 0755 0 0")

    def add(path, source):
        directory(str(Path(path).parent))
        mode = source.lstat().st_mode
        if stat.S_ISLNK(mode):
            records[path] = f"slink {path} {source.readlink()} 0777 0 0"
        elif stat.S_ISDIR(mode):
            directory(path)
        elif stat.S_ISREG(mode):
            if any(c.isspace() for c in str(source)):
                raise ValueError("gen_init_cpio cannot encode whitespace")
            records[path] = f"file {path} {source} {stat.S_IMODE(mode):04o} 0 0"
        else:
            raise ValueError(f"Unexpected store node: {source}")

    for item in a.closure.read_text().splitlines():
        store = Path(item)
        add(item, store)
        if store.is_dir():
            for source in sorted(store.rglob("*")):
                add(str(source), source)
    for name in ("/bin", "/dev", "/proc", "/sys", "/run", "/tmp", "/newroot",
                 "/etc", "/tools"):
        directory(name)
    add("/bin/busybox", a.busybox)
    add("/init", a.init)
    records["/init"] = f"file /init {a.init} 0755 0 0"
    add("/provider.bin", a.provider)
    add("/etc/usb-rndis", a.usb)
    for name, source in sorted(firmware.items()):
        add("/lib/firmware/" + name, source)
    records["/bin/sh"] = "slink /bin/sh busybox 0777 0 0"
    records["/dev/console"] = "nod /dev/console 0600 0 0 c 5 1"
    for name, target in {"kexec": a.kexec / "bin/kexec",
                         "fdtget": a.dtc / "bin/fdtget",
                         "fdtput": a.dtc / "bin/fdtput"}.items():
        records["/tools/" + name] = f"slink /tools/{name} {target} 0777 0 0"
    listing = a.out / "initramfs.list"
    listing.write_text("\n".join(records.values()) + "\n")
    with (a.out / "initramfs.cpio").open("xb") as output:
        subprocess.run([a.cpio, "-t", "0", listing], stdout=output, check=True)


if __name__ == "__main__":
    main()
