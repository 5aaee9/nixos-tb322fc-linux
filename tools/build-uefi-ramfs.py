#!/usr/bin/env python3
"""Build immutable RAM FAT media for the isolated UEFI provider."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_readonly_initrd(directory, meta, common_init, persistent=False):
    """Check the generated single-newc handoff, not arbitrary cpio archives."""
    expected = {
        "init": common_init.read_bytes(),
        "etc/y700-efi-system": (meta["system"] + "\n").encode(),
        "etc/y700-efi-generation": (str(meta["generation"]) + "\n").encode(),
    }
    if not persistent:
        expected["etc/y700-root-readonly"] = b"readonly-overlay\n"
    with gzip.open(directory / "initrd.gz", "rb") as stream:
        data = stream.read(128 * 1024 * 1024 + 1)
    if len(data) > 128 * 1024 * 1024:
        raise ValueError("Initrd exceeds inspection limit")
    offset, paths, regular_inodes, found = 0, {}, set(), set()
    while offset + 110 <= len(data):
        header = data[offset:offset + 110]
        if header[:6] != b"070701":
            raise ValueError("Expected a single newc initrd")
        if any(byte not in b"0123456789abcdefABCDEF" for byte in header[6:]):
            raise ValueError("Nonhex initrd header field")
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        inode, mode, nlink = fields[0], fields[1], fields[4]
        size, devmajor, devminor, namesize = fields[6], fields[7], fields[8], fields[11]
        start = offset + 110
        if not 1 <= namesize <= 4096 or start + namesize > len(data):
            raise ValueError("Invalid initrd name length")
        name = data[start:start + namesize]
        if name[-1:] != b"\0" or b"\0" in name[:-1]:
            raise ValueError("Invalid initrd name")
        name = name[:-1].decode("utf-8")
        start = (start + namesize + 3) & ~3
        end = start + size
        if end > len(data):
            raise ValueError("Truncated initrd entry")
        offset = (end + 3) & ~3
        if offset > len(data):
            raise ValueError("Truncated initrd alignment")
        if name == "TRAILER!!!":
            if mode or size or any(data[offset:]) or found != set(expected):
                raise ValueError("Missing handoff files or appended initrd data")
            return
        kind = stat.S_IFMT(mode)
        if mode > 0xffff or kind not in (
            stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK,
            stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK,
        ):
            raise ValueError("Unsupported initrd node type")
        if kind not in (stat.S_IFREG, stat.S_IFLNK) and size:
            raise ValueError("Initrd directory or special node has a body")
        if kind == stat.S_IFLNK:
            # gen_init_cpio includes a final NUL; the kernel also accepts none.
            target = data[start:end].removesuffix(b"\0")
            if not 1 <= size <= 4096 or not target or b"\0" in target:
                raise ValueError("Invalid initrd symlink body")
        if kind != stat.S_IFDIR and nlink != 1:
            raise ValueError("Initrd hardlink or invalid link count: " + name)
        if not name or name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/")):
            raise ValueError("Noncanonical initrd path")
        if name in paths:
            raise ValueError("Duplicate initrd path")
        if persistent and name == "etc/y700-root-readonly":
            raise ValueError("Persistent initrd contains a read-only marker")
        parts = name.split("/")
        for depth in range(1, len(parts)):
            parent = "/".join(parts[:depth])
            if paths.get(parent) != stat.S_IFDIR:
                raise ValueError("Initrd parent is not a preceding directory: " + parent)
        # Bind records to the paths Linux will unpack, without hardlink aliases.
        if kind == stat.S_IFREG:
            identity = (devmajor, devminor, inode)
            if identity in regular_inodes:
                raise ValueError("Initrd regular-file hardlink or reused inode: " + name)
            regular_inodes.add(identity)
        paths[name] = kind
        if name in expected:
            if not stat.S_ISREG(mode) or data[start:end] != expected[name]:
                raise ValueError("Initrd handoff file mismatch: " + name)
            found.add(name)
    raise ValueError("Missing initrd trailer")


def generation_files(directory, kernel, persistent=False):
    spec = importlib.util.spec_from_file_location(
        "efi_esp", Path(__file__).with_name("build-efi-esp.py"))
    esp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(esp)
    meta = esp.verify_generation(directory)
    mode = "persistent" if persistent else "readonly-overlay"
    if meta.get("root_mode") != mode:
        raise ValueError("NixOS generation root mode does not match the requested media")
    if meta["files"]["linux.efi"] != sha256(kernel):
        raise ValueError("Generation differs from the selected board EFI kernel")
    verify_readonly_initrd(directory, meta, esp.generation.VENDOR / "initramfs/init",
                          persistent=persistent)
    entry = f"nixos-generation-{meta['generation']}.conf"
    # The provider adds live RAM reservations; keep its transformed tree.
    title = "persistent root" if persistent else "RAM overlay"
    text = (f"title NixOS Y700 generation {meta['generation']} ({title})\n"
            f"version {meta['generation']}\nlinux /EFI/Linux/Image\n"
            "initrd /EFI/Linux/nixos-initrd.gz\n"
            f"options {(directory / 'options').read_text().strip()}\n")
    return meta, entry, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--loader", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--busybox", type=Path)
    parser.add_argument("--gen-init-cpio", type=Path)
    parser.add_argument("--default", choices=("a", "b"), default="a")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--target-initrd", type=Path)
    target.add_argument("--generation", type=Path)
    parser.add_argument("--persistent-root", action="store_true",
                        help="explicitly allow a generation that writes the installed rootfs")
    parser.add_argument("--cmdline", type=Path)
    args = parser.parse_args()
    if args.persistent_root and not args.generation:
        parser.error("--persistent-root requires --generation")
    args.out.mkdir(parents=True, exist_ok=False)
    output = args.out.resolve()
    spec = importlib.util.spec_from_file_location(
        "efi_lab", Path(__file__).with_name("test-efi-chain.py"))
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    files = {"EFI/BOOT/BOOTAA64.EFI": args.loader,
             "EFI/Linux/Image": args.kernel}
    generation_meta = None
    if args.generation:
        generation_meta, default, text = generation_files(
            args.generation, args.kernel, args.persistent_root)
        conf = output / default
        conf.write_text(text)
        files["EFI/Linux/nixos-initrd.gz"] = args.generation / "initrd.gz"
        files[f"loader/entries/{default}"] = conf
    elif args.target_initrd:
        if not args.cmdline:
            parser.error("target initrd requires the board command line")
        options = [x for x in args.cmdline.read_text().split()
                   if not x.startswith(("root=", "init=", "rdinit=", "y700."))
                   and x != "efi=noruntime"]
        options += ["rdinit=/init", "y700.efi-diag=v1"]
        files["EFI/Linux/diagnostic.cpio"] = args.target_initrd
        conf = output / "y700-efi-diag.conf"
        conf.write_text(
            "title TB322FC EFI diagnostic (RAM)\nversion 1\n"
            "linux /EFI/Linux/Image\ninitrd /EFI/Linux/diagnostic.cpio\n"
            f"options {' '.join(options)}\n")
        files["loader/entries/y700-efi-diag.conf"] = conf
        default = "y700-efi-diag.conf"
    else:
        if not args.busybox or not args.gen_init_cpio:
            parser.error("lab requires busybox and gen-init-cpio")
        for entry in ("a", "b"):
            files[f"EFI/Linux/initrd-{entry}.cpio"] = lab.initramfs(
                output, entry, args.busybox, args.gen_init_cpio)
            conf = output / f"lab-{entry}.conf"
            conf.write_text(
                f"title RAM UEFI test {entry.upper()}\n"
                f"version {entry}\nlinux /EFI/Linux/Image\n"
                f"initrd /EFI/Linux/initrd-{entry}.cpio\n"
                f"options console=ttyAMA0 rdinit=/init panic=5 y700.lab-generation={entry}\n")
            files[f"loader/entries/lab-{entry}.conf"] = conf
        default = f"lab-{args.default}.conf"
    config = output / "loader.conf"
    config.write_text(f"default {default}\ntimeout 2\neditor no\n"
                      "auto-firmware no\nauto-entries no\nrandom-seed-mode off\n"
                      "console-mode keep\n")
    files["loader/loader.conf"] = config
    image = output / "ramfs.img"
    size = 96 * 1024 * 1024
    if sum(p.stat().st_size for p in files.values()) > size - 8 * 1024 * 1024:
        raise ValueError("RAM FAT payload exceeds fixed media capacity")
    with image.open("xb") as stream:
        stream.truncate(size)
    env = os.environ | {"MTOOLSRC": "/dev/null", "TZ": "UTC",
                        "SOURCE_DATE_EPOCH": "1793664000"}

    def run(*argv):
        subprocess.run(["faketime", "-f", "2026-11-03 00:00:00",
                        *[str(x) for x in argv]], check=True, env=env)

    run("mkfs.fat", "--invariant", "-F", "32", "-i", "59554649", "-n", "Y700RAM", image)
    run("mmd", "-i", image, "::/EFI", "::/EFI/BOOT", "::/EFI/Linux",
        "::/loader", "::/loader/entries")
    staging = output / "staging"
    staging.mkdir()
    for index, (destination, source) in enumerate(files.items()):
        staged = staging / str(index)
        shutil.copyfile(source, staged)
        os.utime(staged, (1793664000, 1793664000))
        run("mcopy", "-m", "-i", image, staged, f"::/{destination}")
    with image.open("rb") as source, (output / "ramfs.img.gz").open("xb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
            while chunk := source.read(1024 * 1024):
                compressed.write(chunk)
    (output / "metadata.json").write_text(json.dumps({
        "scope": ("TB322FC read-only NixOS RAM candidate; unvalidated on target" if args.generation
                  else "TB322FC rootless diagnostic; unvalidated on target" if args.target_initrd
                  else "QEMU lab; synthetic RAM initrds, not tablet or NixOS acceptance"),
        "default": default if args.target_initrd or args.generation else args.default,
        "generation": generation_meta,
        "bytes": size, "sha256": sha256(image),
        "compressed_sha256": sha256(output / "ramfs.img.gz"),
        "files": {name: sha256(path) for name, path in files.items()},
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
