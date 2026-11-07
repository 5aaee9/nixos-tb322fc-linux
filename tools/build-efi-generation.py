#!/usr/bin/env python3
"""Package a board kernel, firmware initrd, DTB and exact NixOS system offline."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
VENDOR = PROJECT / "vendor/tb322fc-linux"
SYSTEM_RE = r"/nix/store/[0-9a-df-np-sv-z]{32}-nixos-system-[a-zA-Z0-9.+_-]+"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pe_machine(path):
    with Path(path).open("rb") as stream:
        header = stream.read(64)
        require(header[:2] == b"MZ" and len(header) == 64, "Not a PE image")
        stream.seek(struct.unpack_from("<I", header, 0x3c)[0])
        pe = stream.read(26)
    require(pe[:4] == b"PE\0\0" and len(pe) == 26, "Missing PE header")
    require(struct.unpack_from("<H", pe, 24)[0] == 0x20b, "Not PE32+")
    return struct.unpack_from("<H", pe, 4)[0]


def verify_kernel(directory):
    metadata = json.loads((directory / "metadata.json").read_text())
    expected = json.loads((VENDOR / "sources.json").read_text())["kernel"]
    require(metadata["schema"] == 1 and metadata["kernel"] == expected, "Kernel source pin mismatch")
    for name in ("Image", "elden.dtb", "kernel.config", "kernel.release"):
        require(sha(directory / name) == metadata["files"][name], "Kernel checksum: " + name)
    config = set((directory / "kernel.config").read_text().splitlines())
    require({'CONFIG_EFI=y', 'CONFIG_EFI_STUB=y', 'CONFIG_INITRAMFS_SOURCE=""',
             'CONFIG_CMDLINE=""', 'CONFIG_BLK_DEV_INITRD=y'}.issubset(config),
            "Kernel must use EFI with an external initrd and loader command line")
    require("CONFIG_CMDLINE_FORCE=y" not in config, "Forced kernel command line")
    require("CONFIG_BUILTIN_DTB=y" not in config, "Built-in DTB overrides EFI handoff")
    require(pe_machine(directory / "Image") == 0xaa64, "Kernel is not ARM64 PE")
    require((directory / "elden.dtb").read_bytes()[:4] == b"\xd0\x0d\xfe\xed", "Invalid DTB magic")
    return metadata


def command_line(system, generation, usb_debug=False):
    require(re.fullmatch(SYSTEM_RE, system), "Invalid NixOS system path")
    require(type(generation) is int and generation > 0, "Invalid generation number")
    options = (VENDOR / "configs/cmdline.txt").read_text().split()
    options = [x for x in options if x != "efi=noruntime" and
               not x.startswith(("init=", "panic=", "y700.", "dtb=", "initrd="))]
    require(options.count("root=PARTLABEL=rootfs") == 1 and options.count("rdinit=/init") == 1,
            "Unexpected board handoff command line")
    options += ["panic=30", "init=" + system + "/init",
                "y700.system=" + system, "y700.generation=" + str(generation)]
    if usb_debug:
        options.append("y700.usb-debug=1")
    return " ".join(options)


def esp_namespace(generation, kernel_hash, initrd_hash, dtb_hash):
    require(type(generation) is int and generation > 0, "Invalid generation number")
    for value in (kernel_hash, initrd_hash, dtb_hash):
        require(re.fullmatch(r"[0-9a-f]{64}", value), "Invalid artifact hash")
    identity = hashlib.sha256(
        f"{generation}:{kernel_hash}:{initrd_hash}:{dtb_hash}".encode("ascii")).hexdigest()
    return f"EFI/nixos/{generation}-{identity}"


def build_initrd(output, system, generation, firmware_dir=None, busybox=None,
                 gen_init_cpio=None, readonly_root=False):
    (output / "system-path").write_text(system + "\n")
    (output / "generation-number").write_text(str(generation) + "\n")
    listing = (VENDOR / "configs/initramfs-tb322fc-prc.list").read_text()
    listing += (
        "\nfile /etc/usb-rndis ${PROJECT}/initramfs/usb-rndis 0444 0 0\n"
        f"file /etc/y700-efi-system {output}/system-path 0444 0 0\n"
        f"file /etc/y700-efi-generation {output}/generation-number 0444 0 0\n"
    )
    if readonly_root:
        (output / "root-readonly").write_text("readonly-overlay\n")
        listing += f"file /etc/y700-root-readonly {output}/root-readonly 0444 0 0\n"
    (output / "initramfs.list").write_text(listing)
    env = os.environ | {"PROJECT": str(VENDOR),
                        "FIRMWARE_DIR": str(firmware_dir or VENDOR / "inputs/firmware"),
                        "BUSYBOX": str(busybox or VENDOR / "build/busybox/busybox")}
    raw = subprocess.check_output([str(gen_init_cpio or VENDOR / "build/gen_init_cpio"), "-t", "0",
                                   str(output / "initramfs.list")], env=env)
    # gzip.compress may include platform-specific header bytes on older Python.
    with (output / "initrd.gz").open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
            compressed.write(raw)
    return len(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--system", required=True, type=Path)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--usb-debug", action="store_true")
    parser.add_argument("--readonly-root", action="store_true",
                        help="protect all UFS nodes and use a volatile root overlay")
    parser.add_argument("--firmware", type=Path, default=VENDOR / "inputs/firmware")
    parser.add_argument("--busybox", type=Path, default=VENDOR / "build/busybox/busybox")
    parser.add_argument("--gen-init-cpio", type=Path, default=VENDOR / "build/gen_init_cpio")
    args = parser.parse_args()
    output = args.out.absolute()
    require(not output.exists(), "Output directory must be new")
    require(not any(c.isspace() for c in str(output)), "gen_init_cpio paths cannot contain whitespace")
    kernel = args.kernel.resolve(strict=True)
    kernel_meta = verify_kernel(kernel)
    system = str(args.system.resolve(strict=True))
    require(re.fullmatch(SYSTEM_RE, system), "Not a NixOS system store path")
    spec = json.loads((Path(system) / "boot.json").read_text())["org.nixos.bootspec.v1"]
    require(spec["system"] == "aarch64-linux" and spec["toplevel"] == system and
            spec["init"] == system + "/init", "NixOS bootspec identity/architecture")
    require((Path(system) / "etc/systemd/system/y700-local-root-prepare-shutdown.service").exists(),
            "Use the persistent NixOS system")
    firmware = json.loads((VENDOR / "firmware-tb322fc-prc.json").read_text())
    for item in firmware["files"]:
        require(sha(args.firmware / item["path"]) == item["sha256"],
                "Matching own-tablet firmware is required: " + item["path"])
    options = command_line(system, args.generation, args.usb_debug)
    output.mkdir(parents=True)
    shutil.copyfile(kernel / "Image", output / "linux.efi")
    shutil.copyfile(kernel / "elden.dtb", output / "elden.dtb")
    size = build_initrd(output, system, args.generation, args.firmware, args.busybox,
                        args.gen_init_cpio, args.readonly_root)
    (output / "options").write_text(options + "\n")
    namespace = esp_namespace(args.generation, sha(output / "linux.efi"),
                              sha(output / "initrd.gz"), sha(output / "elden.dtb"))
    # Export an accurate board bootspec separately from the installed system's
    # generic one. This command does not modify a store path or system profile.
    board_spec = {"org.nixos.bootspec.v1": spec | {
        "kernel": f"/boot/{namespace}/linux.efi",
        "initrd": f"/boot/{namespace}/initrd.gz", "kernelParams": options.split(),
        "label": f"NixOS Y700 generation {args.generation} ({kernel_meta['release']})"},
        "org.y700.board.v1": {"dtb": f"/boot/{namespace}/elden.dtb",
                             "generation": args.generation,
                             "path_scope": "intended target ESP mounted at /boot"}}
    (output / "boot.json").write_text(json.dumps(board_spec, indent=2) + "\n")
    meta = {
        "schema": 1, "generation": args.generation, "system": system,
        "esp_namespace": namespace,
        "kernel": kernel_meta, "initrd_uncompressed_bytes": size,
        "firmware_manifest_sha256": sha(VENDOR / "firmware-tb322fc-prc.json"),
        "nixpkgs": json.loads((PROJECT / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"],
        "scope": "offline board EFI generation; no tablet boot or installation",
        "root_mode": "readonly-overlay" if args.readonly_root else "persistent",
        "gen_init_cpio_sha256": sha(args.gen_init_cpio),
        "diagnostics": "USB development access" if args.usb_debug else "USB gadget disabled",
        "files": {name: sha(output / name) for name in
                  ("linux.efi", "elden.dtb", "initrd.gz", "options", "boot.json",
                   "system-path", "generation-number")},
        "source_sha256": {str(path.relative_to(PROJECT)): sha(path) for path in
                         (Path(__file__).resolve(), VENDOR / "initramfs/init",
                          VENDOR / "initramfs/usb-rndis", VENDOR / "configs/initramfs-tb322fc-prc.list")},
        "busybox_sha256": sha(args.busybox),
    }
    (output / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name, value in meta["files"].items()))
    print(f"Prepared EFI generation {args.generation}: {output}")


if __name__ == "__main__":
    main()
