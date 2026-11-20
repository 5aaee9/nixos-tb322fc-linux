#!/usr/bin/env python3
"""Publish board BLS entries as an atomic FAT snapshot for the Linux reader."""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SYSTEM = re.compile(r"/nix/store/[0-9a-df-np-sv-z]{32}-nixos-system-[a-zA-Z0-9.+_-]+")
SNAPSHOT = re.compile(r"[1-9][0-9]*-[0-9a-f]{64}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity_archive(system, generation):
    """A second newc archive binds the immutable stage1 to one exact entry."""
    output = bytearray()
    items = [
        ("etc/y700-efi-system", (system + "\n").encode()),
        ("etc/y700-efi-generation", (str(generation) + "\n").encode()),
        ("TRAILER!!!", b""),
    ]
    for inode, (name, data) in enumerate(items, 1):
        encoded = name.encode() + b"\0"
        mode = 0 if name == "TRAILER!!!" else 0o100444
        fields = (inode, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0)
        output += b"070701" + b"".join(f"{v:08x}".encode() for v in fields)
        output += encoded
        output += b"\0" * (-len(output) % 4)
        output += data
        output += b"\0" * (-len(output) % 4)
    output += b"\0" * (-len(output) % 512)
    return bytes(output)


def options(base, system, generation, debug):
    require(SYSTEM.fullmatch(system), "Invalid toplevel")
    require(type(generation) is int and 0 < generation < 2**31, "Invalid generation")
    args = [x for x in base.split() if x != "efi=noruntime" and
            not x.startswith(("init=", "panic=", "y700.", "dtb=", "initrd="))]
    require(args.count("root=PARTLABEL=rootfs") == 1 and args.count("rdinit=/init") == 1,
            "Invalid board root command line")
    args += ["panic=30", f"init={system}/init", f"y700.system={system}",
             f"y700.generation={generation}"]
    if debug:
        args.append("y700.usb-debug=1")
    return " ".join(args)


def load_payload(system, override=None):
    require(SYSTEM.fullmatch(str(system)), "Invalid system path")
    path = override if override is not None else system / "y700-boot"
    meta = json.loads((path / "metadata.json").read_text())
    require(meta["schema"] == 1 and meta["board"] == "lenovo,elden", "Invalid board artifacts")
    for name, expected in meta["files"].items():
        require(name in ("Image", "elden.dtb", "initramfs.cpio", "systemd-bootaa64.efi",
                         "cmdline"), "Unexpected artifact")
        require(digest(path / name) == expected, "Artifact checksum: " + name)
    require(set(meta["files"]) == {"Image", "elden.dtb", "initramfs.cpio",
                                 "systemd-bootaa64.efi", "cmdline"}, "Missing artifacts")
    require((path / "Image").read_bytes()[56:60] == b"ARM\x64", "Not an ARM64 kernel")
    return path, meta


def assemble(output, systems, default, debug, artifact_override=None):
    tree = output / "tree"
    for name in ("EFI/BOOT", "EFI/nixos", "loader/entries"):
        (tree / name).mkdir(parents=True, exist_ok=True)
    entries = {}
    dtb_hash = loader_hash = None
    for number, system in sorted(systems.items()):
        payload, meta = load_payload(system, artifact_override)
        if dtb_hash is None:
            dtb_hash, loader_hash = meta["files"]["elden.dtb"], meta["files"]["systemd-bootaa64.efi"]
        require(meta["files"]["elden.dtb"] == dtb_hash,
                "DTB update needs a reviewed runtime-fixup/bootstrap update")
        kernel_name = f"EFI/nixos/{meta['files']['Image']}.efi"
        if not (tree / kernel_name).exists():
            shutil.copyfile(payload / "Image", tree / kernel_name)
        initrd_name = f"EFI/nixos/initrd-{number}.gz"
        with (tree / initrd_name).open("xb") as stream:
            with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as gz:
                with (payload / "initramfs.cpio").open("rb") as base:
                    shutil.copyfileobj(base, gz)
                gz.write(identity_archive(str(system), number))
        line = options((payload / "cmdline").read_text(), str(system), number, debug)
        (tree / f"loader/entries/nixos-generation-{number}.conf").write_text(
            f"title NixOS generation {number}\nversion {number}\nsort-key nixos\n"
            f"linux /{kernel_name}\ninitrd /{initrd_name}\noptions {line}\n")
        entries[str(number)] = {
            "system": str(system), "kernel": meta["files"]["Image"],
            "initrd": digest(tree / initrd_name), "payload": str(payload.resolve()),
        }
    payload, selected = load_payload(systems[default], artifact_override)
    loader_hash = selected["files"]["systemd-bootaa64.efi"]
    shutil.copyfile(payload / "systemd-bootaa64.efi", tree / "EFI/BOOT/BOOTAA64.EFI")
    (tree / "loader/loader.conf").write_text(
        f"default nixos-generation-{default}.conf\ntimeout 2\neditor no\n"
        "auto-entries no\nauto-firmware no\nrandom-seed-mode off\nconsole-mode keep\n")
    total = sum(p.stat().st_size for p in tree.rglob("*") if p.is_file())
    size = max(96 << 20, ((total + (32 << 20) - 1) // (32 << 20) + 1) * (32 << 20))
    require(size <= 1 << 30, "Boot snapshot exceeds the bootstrap RAM contract")
    image = output / "esp.img"
    with image.open("xb") as stream:
        stream.truncate(size)
    env = os.environ | {"MTOOLSRC": "/dev/null"}
    subprocess.run(["mkfs.fat", "--invariant", "-F", "32", "-S", "512",
                    "-n", "Y700BOOT", str(image)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["mcopy", "-s", "-i", str(image), str(tree / "EFI"),
                    str(tree / "loader"), "::/"], env=env, check=True)
    hashes = {}
    for path in sorted(tree.rglob("*")):
        if not path.is_file():
            continue
        name = str(path.relative_to(tree))
        hashes[name] = digest(path)
        copied = subprocess.check_output(["mtype", "-i", str(image), "::/" + name], env=env)
        require(hashlib.sha256(copied).hexdigest() == hashes[name], "FAT readback: " + name)
    subprocess.run(["fsck.fat", "-n", str(image)], check=True, stdout=subprocess.DEVNULL)
    image_hash = digest(image)
    (output / "esp.sha256").write_text(f"{image_hash}  esp.img\n")
    manifest = {"schema": 1, "default": default, "generations": entries, "usb_debug": debug,
                "dtb": dtb_hash, "loader": loader_hash, "image_sha256": image_hash,
                "image_bytes": size, "files": hashes}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.rmtree(tree)
    return manifest


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def checked_snapshot(base, path):
    require(path.parent == base / "snapshots" and SNAPSHOT.fullmatch(path.name),
            "Invalid snapshot path")
    require(not path.is_symlink() and path.is_dir(), "Snapshot must be a directory")
    files = {"manifest.json", "esp.img", "esp.sha256"}
    require({p.name for p in path.iterdir()} == files, "Unexpected snapshot contents")
    for item in [path] + [path / name for name in files]:
        require(not item.is_symlink() and item.stat().st_uid == os.geteuid() and
                not item.stat().st_mode & 0o022, "Untrusted snapshot ownership")
    meta = json.loads((path / "manifest.json").read_text())
    require(meta["schema"] == 1 and
            path.name == f"{meta['default']}-{meta['image_sha256']}",
            "Snapshot manifest mismatch")
    require((path / "esp.sha256").read_text() == f"{meta['image_sha256']}  esp.img\n" and
            (path / "esp.img").stat().st_size == meta["image_bytes"],
            "Snapshot image metadata mismatch")
    for n, entry in meta["generations"].items():
        require(re.fullmatch(r"[1-9][0-9]*", n) and SYSTEM.fullmatch(entry["system"]),
                "Invalid snapshot generation")
    require(str(meta["default"]) in meta["generations"], "Snapshot has no default entry")
    return meta


def prune_snapshots(base, gcbase):
    """Only remove our validated snapshots after both retained pointers are durable."""
    require(gcbase.is_dir() and not gcbase.is_symlink() and
            gcbase.stat().st_uid == os.geteuid() and not gcbase.stat().st_mode & 0o022,
            "Untrusted GC-root directory")
    keep = set()
    for name in ("current", "previous"):
        link = base / name
        if not link.exists() and not link.is_symlink() and name == "previous":
            continue
        require(link.is_symlink(), "Retained snapshot pointer must be a symlink")
        target = link.resolve(strict=True)
        meta = checked_snapshot(base, target)
        require(digest(target / "esp.img") == meta["image_sha256"], "Retained FAT is corrupt")
        keep.add(target)
    remove = []
    for path in (base / "snapshots").iterdir():
        meta = checked_snapshot(base, path)
        roots = gcbase / path.name
        require(roots.is_dir() and not roots.is_symlink() and
                roots.stat().st_uid == os.geteuid() and not roots.stat().st_mode & 0o022,
                "Untrusted snapshot GC roots")
        require({p.name for p in roots.iterdir()} == set(meta["generations"]),
                "Snapshot GC roots do not match its manifest")
        for n, entry in meta["generations"].items():
            link = roots / n
            require(link.is_symlink() and os.readlink(link) == entry["system"],
                    "Unexpected snapshot GC reference")
        if path not in keep:
            remove.append((path, roots))
    # Validate the entire deletion set before removing any rollback artifact.
    for path, roots in remove:
        for name in ("esp.img", "esp.sha256", "manifest.json"):
            (path / name).unlink()
        path.rmdir()
        for link in roots.iterdir():
            link.unlink()
        roots.rmdir()
    sync_directory(base / "snapshots")
    sync_directory(gcbase)


def install(system, limit, debug, root=Path("/")):
    require(os.geteuid() == 0, "Boot installation requires root")
    require(root == Path("/"), "Production installation only supports the actual root")
    require(b"lenovo,elden\0" in Path("/proc/device-tree/compatible").read_bytes(), "Wrong board")
    require(subprocess.check_output(["findmnt", "-n", "-o", "FSTYPE", "/"]).strip() == b"btrfs",
            "Boot snapshots require the installed Btrfs root")
    require(Path("/etc/y700-rootfs-contract").read_text().strip() == "tb322fc-rootfs-v1",
            "Missing installed root contract")
    profiles = Path("/nix/var/nix/profiles")
    require((profiles / "system").resolve(strict=True) == system, "Profile does not select requested system")
    active = re.fullmatch(r"system-([1-9][0-9]*)-link", os.readlink(profiles / "system"))
    require(active, "Invalid system profile link")
    number = int(active[1])
    systems = {number: system}
    for link in sorted(profiles.glob("system-*-link"),
                       key=lambda p: int(p.name.split("-")[1]), reverse=True):
        if len(systems) >= limit:
            break
        n = int(link.name.split("-")[1])
        target = link.resolve(strict=True)
        if n == number or not (target / "y700-boot/metadata.json").exists():
            continue
        systems[n] = target
        if len(systems) >= limit:
            break
    base = Path("/boot/y700")
    gcbase = Path("/nix/var/nix/gcroots/y700-boot")
    for directory in (Path("/boot"), base, base / "snapshots"):
        require(not directory.is_symlink(), "Boot directory must not be a symlink")
        directory.mkdir(mode=0o755, exist_ok=True)
        require(directory.stat().st_uid == 0 and not directory.stat().st_mode & 0o022 and
                directory.stat().st_dev == root.stat().st_dev,
                "Boot directory must be root-owned on the root filesystem")
    contract_file = base / "bootstrap.json"
    require(contract_file.is_file() and not contract_file.is_symlink() and
            contract_file.stat().st_uid == 0 and not contract_file.stat().st_mode & 0o022,
            "A verified bootstrap installation contract is required")
    contract = json.loads(contract_file.read_text())
    _, requested_payload = load_payload(system)
    require(contract["schema"] == 1 and contract["media"] == "fat-v1" and
            contract["source_dtb_sha256"] == requested_payload["files"]["elden.dtb"],
            "Board DTB is not compatible with the installed bootstrap")
    with (base / ".install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current = base / "current"
        if current.exists() or current.is_symlink():
            require(current.is_symlink() and current.resolve().parent == base / "snapshots",
                    "Current snapshot must be a local snapshot link")
            old = checked_snapshot(base, current.resolve())
            _, new = load_payload(system)
            require(old["dtb"] == new["files"]["elden.dtb"], "DTB changes require bootstrap review")
            desired = {str(n): str(target) for n, target in systems.items()}
            if (old["default"] == number and old.get("usb_debug") == debug and
                    {n: e["system"] for n, e in old["generations"].items()} == desired):
                require(digest(current / "esp.img") == old["image_sha256"], "Current FAT is corrupt")
                subprocess.run(["sync", "-f", str(base)], check=True)
                prune_snapshots(base, gcbase)
                print(f"Generation {number} is already published and verified")
                return
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=base))
        try:
            meta = assemble(staging, systems, number, debug)
            for file in staging.iterdir():
                with file.open("rb") as stream:
                    os.fsync(stream.fileno())
            sync_directory(staging)
            name = f"{number}-{meta['image_sha256']}"
            destination = base / "snapshots" / name
            require(not destination.exists(), "Snapshot already exists; inspect prior installation")
            roots = gcbase / name
            roots.mkdir(parents=True)
            for n, target in systems.items():
                (roots / str(n)).symlink_to(target)
            sync_directory(roots)
            sync_directory(gcbase)
            staging.rename(destination)
            sync_directory(destination.parent)
            if current.is_symlink():
                previous = base / ".previous-next"
                require(not previous.exists() and not previous.is_symlink(), "Stale previous pointer")
                previous.symlink_to(os.readlink(current))
                os.replace(previous, base / "previous")
            next_link = base / ".current-next"
            require(not next_link.exists() and not next_link.is_symlink(), "Stale publication pointer")
            next_link.symlink_to("snapshots/" + name)
            os.replace(next_link, current)
            sync_directory(base)
            # Commit the Btrfs transaction before a reader suppresses log replay.
            subprocess.run(["sync", "-f", str(base)], check=True)
            prune_snapshots(base, gcbase)
            print(f"Published systemd-boot generation {number}: {destination}")
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("system", type=Path)
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--usb-debug", action="store_true")
    p.add_argument("--prepare", type=Path, help="Build an offline candidate without installing")
    p.add_argument("--generation", type=int, help="Generation for an offline candidate")
    p.add_argument("--artifacts", type=Path, help="Board artifacts for an offline candidate")
    a = p.parse_args()
    system = a.system.resolve(strict=True)
    require(1 <= a.limit <= 8, "Retention must be between 1 and 8")
    if a.prepare:
        require(a.generation is not None, "Offline preparation needs a generation")
        a.prepare.mkdir()
        assemble(a.prepare, {a.generation: system}, a.generation, a.usb_debug, a.artifacts)
    else:
        require(a.generation is None, "Production generations come from the system profile")
        require(a.artifacts is None, "Production artifacts come from each system")
        install(system, a.limit, a.usb_debug)


if __name__ == "__main__":
    main()
