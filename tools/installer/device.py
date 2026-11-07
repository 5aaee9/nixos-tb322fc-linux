#!/usr/bin/env python3
"""Device half of the TB322FC installer. Run only through install-nixos.py."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import time

BASE = Path(__file__).resolve().parent
TOOLS = BASE if (BASE / "storage-layout.py").exists() else BASE.parent
LABELS = ("metadata", "misc", "boot_a", "boot_b", "vendor_boot_a", "vendor_boot_b",
          "init_boot_a", "init_boot_b", "recovery_a", "recovery_b", "abl_a", "abl_b")
RECOVERY_SHA256 = "3fc66edd5166971568811ea73221f42a3bc6637930e2a7f2c4efb2a4297585c0"


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), TOOLS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


writer = load("prepare-storage-write")
reset = load("prepare-recovery-reset")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True,
                          text=True, **kwargs).stdout.strip()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def event(name, **values):
    print(json.dumps({"event": name, "device_time": time.time(), **values}), flush=True)


def write_json(path, value):
    with Path(path).open("x") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def check_unused(nodes):
    devices = {(node / "dev").read_text().strip() for node in nodes}
    namespaces = set()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            namespace = (proc / "ns/mnt").stat().st_ino
            if namespace in namespaces:
                continue
            text = (proc / "mountinfo").read_text()
            namespaces.add(namespace)
        except FileNotFoundError:
            continue
        for line in text.splitlines():
            require(line.split()[2] not in devices, "Internal device mounted in a namespace")
    for node in nodes:
        require(not list((node / "holders").iterdir()), "Internal device has holders")
    require(len(Path("/proc/swaps").read_text().splitlines()) == 1, "Active swap")


def identity(request, persistent=False):
    require(os.geteuid() == 0, "Device installer needs root")
    require(Path("/sys/firmware/devicetree/base/model").read_bytes().rstrip(b"\0") ==
            b"Lenovo Legion Y700 Gen4", "Wrong board")
    expected_root = "root=PARTLABEL=rootfs" if persistent else "root=usb-nbd"
    require(expected_root in Path("/proc/cmdline").read_text().split(), "Wrong boot mode")
    system = str(Path("/run/current-system").resolve())
    require(system == request["system"], "Unexpected NixOS system")
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if request.get("boot_id"):
        require(boot_id == request["boot_id"], "Boot identity changed")
    capacities = [int(p.read_text()) for p in Path("/sys/class/power_supply").glob("*/capacity")]
    require(capacities and min(capacities) >= 50, "Battery must be at least 50 percent")
    return {"system": system, "boot_id": boot_id, "battery": min(capacities)}


def capture():
    result = []
    for node in sorted(Path("/sys/class/block").glob("sd*")):
        if (node / "partition").exists():
            continue
        lun = str((node / "device").resolve())
        require("/1d84000.ufs/" in lun, "Unexpected non-UFS disk")
        sector = int((node / "queue/logical_block_size").read_text())
        size = int((node / "size").read_text()) * 512
        require(sector == 4096, "Wrong logical sector size")
        fd = os.open("/dev/" + node.name, os.O_RDONLY | os.O_CLOEXEC)
        try:
            regions = {"pmbr": (0, sector), "primary_header": (sector, sector),
                       "backup_header": (size - sector, sector)}
            for tag, offset in [("primary_entries", sector), ("backup_entries", size - sector)]:
                raw = os.pread(fd, sector, offset)
                h = writer.layout.header(raw, sector, size // sector, offset // sector)
                regions[tag] = (h["table_lba"] * sector, h["count"] * h["entry_size"])
            item = {"schema": 1, "system": str(Path("/run/current-system").resolve()),
                    "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    "disk_path": "/dev/" + node.name, "controller_lun": lun,
                    "sector_size": sector, "disk_bytes": size, "regions": {}}
            for name, (offset, length) in regions.items():
                value = os.pread(fd, length, offset)
                require(len(value) == length and value == os.pread(fd, length, offset),
                        "GPT changed while reading")
                item["regions"][name] = writer.region(value, offset)
            writer.layout.decode_capture(item, allow_vendor_reservations=True)
            result.append(item)
        finally:
            os.close(fd)
    require(len(result) == 6, "Expected six UFS LUNs")
    return result


def compare_gpts(actual, expected):
    by_lun = {c["controller_lun"]: c for c in expected}
    require(len(actual) == len(by_lun) == 6, "GPT/LUN count changed")
    for item in actual:
        old = by_lun.get(item["controller_lun"])
        require(old is not None, "Unexpected LUN")
        for name in ("disk_bytes", "sector_size", "regions"):
            require(item[name] == old[name], "GPT or geometry differs: " + name)


def check_geometry(captures):
    all_labels = {}
    for item in captures:
        node = Path("/sys/class/block") / Path(item["disk_path"]).name
        _, partitions = writer.layout.decode_capture(item, allow_vendor_reservations=True)
        if any(p["label"] == "userdata" for p in partitions):
            writer.layout.decode_capture(item)
        children = {int((p / "partition").read_text()): p for p in node.resolve().iterdir()
                    if (p / "partition").is_file()}
        require(set(children) == {p["number"] for p in partitions}, "Kernel partition count")
        for part in partitions:
            child = children[part["number"]]
            require(int((child / "start").read_text()) * 512 == part["start"] * 4096,
                    "Kernel partition start")
            require(int((child / "size").read_text()) * 512 == part["sectors"] * 4096,
                    "Kernel partition size")
            require(part["label"] not in all_labels, "Duplicate partition label")
            path = Path("/dev/disk/by-partlabel") / part["label"]
            require(path.resolve(strict=True).name == child.name, "Wrong partlabel symlink")
            all_labels[part["label"]] = part | {"device": str(path.resolve()), "disk": item}
    return all_labels


def partition_hashes():
    values = {}
    for label in LABELS:
        path = Path("/dev/disk/by-partlabel") / label
        size = int(run("blockdev", "--getsize64", path))
        require(0 < size <= 128 * 1024 ** 2, "Unexpected backup size")
        values[label] = {"bytes": size, "sha256": digest(path)}
    return values


def assert_stock(values):
    require(all(values[name]["sha256"] == RECOVERY_SHA256
                for name in ("recovery_a", "recovery_b")),
            "Recovery is not the binary whose reset behavior was verified")
    require(values["misc"]["bytes"] == 1048576 and values["metadata"]["bytes"] == 67108864,
            "Unsupported misc/metadata size")


def check_metadata_idle():
    image = BASE / "metadata-check.img"
    require(not image.exists(), "Metadata check already attempted")
    with Path("/dev/disk/by-partlabel/metadata").open("rb") as src, image.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    os.chmod(image, 0o600)
    require(digest(image) == digest("/dev/disk/by-partlabel/metadata"), "Metadata capture changed")
    loop = run("losetup", "--find", "--show", "--read-only", "--sector-size", "4096", image)
    mount = BASE / "metadata-check"
    mount.mkdir()
    mounted = False
    try:
        require(run("blockdev", "--getro", loop) == "1", "Metadata loop is writable")
        run("mount", "-t", "f2fs", "-o", "ro,norecovery", loop, mount)
        mounted = True
        ota = mount / "ota"
        for path in ota.rglob("*") if ota.exists() else []:
            require(not path.is_symlink(), "OTA state has symlink")
            if path.is_file():
                require(path.relative_to(ota).as_posix() == "state" and path.stat().st_size == 0,
                        "Pending or unsupported OTA/snapshot state")
    finally:
        if mounted:
            run("umount", mount)
        run("losetup", "--detach", loop)
    image.unlink()


def smoke_tools():
    """Use sparse RAM files, never the UFS targets, for formatter/extractor tests."""
    root = BASE / "smoke"
    root.mkdir()
    src = root / "source"
    src.mkdir()
    (src / "tmp").mkdir()
    (src / "tmp").chmod(0o1777)
    (src / "data").write_bytes(b"Y700_INSTALL_SMOKE\n")
    os.chown(src / "data", 1000, 100)
    (src / "data").chmod(0o640)
    os.setxattr(src / "data", b"user.y700test", b"preserve")
    os.link(src / "data", src / "hardlink")
    (src / "link").symlink_to("data")
    archive = root / "test.tar"
    run("tar", "--numeric-owner", "--xattrs", "--acls", "-C", src, "-cpf", archive, ".")
    for kind, size in [("ext4", 128 * 1024 ** 2), ("vfat", 1024 ** 3)]:
        image, mount = root / (kind + ".img"), root / kind
        with image.open("xb") as stream:
            stream.truncate(size)
        loop = run("losetup", "--find", "--show", "--sector-size", "4096", image)
        mount.mkdir()
        mounted = False
        try:
            if kind == "ext4":
                run("mkfs.ext4", "-F", "-m", "0", "-E",
                    "nodiscard,lazy_itable_init=0,lazy_journal_init=0", loop)
            else:
                run("mkfs.fat", "-F", "32", "-S", "4096", loop)
            run("mount", "-t", kind, loop, mount)
            mounted = True
            if kind == "ext4":
                run("tar", "--numeric-owner", "--xattrs", "--acls", "--same-owner",
                    "--same-permissions", "-C", mount, "-xpf", archive)
                data = (mount / "data").stat()
                require((data.st_uid, data.st_gid, data.st_mode & 0o7777) == (1000, 100, 0o640),
                        "Tar ownership/mode smoke test")
                require(data.st_ino == (mount / "hardlink").stat().st_ino, "Hardlink smoke test")
                require(os.readlink(mount / "link") == "data", "Symlink smoke test")
                require((mount / "tmp").stat().st_mode & 0o7777 == 0o1777, "Sticky bit smoke test")
                require(os.getxattr(mount / "data", b"user.y700test") == b"preserve",
                        "Xattr smoke test")
            else:
                (mount / "TEST.TXT").write_text("ESP test\n")
            run("sync", "-f", mount)
            run("umount", mount)
            mounted = False
            run(*(["e2fsck", "-f", "-n", loop] if kind == "ext4" else ["fsck.fat", "-n", loop]))
        finally:
            if mounted:
                run("umount", mount)
            run("losetup", "--detach", loop)
        image.unlink()


def inspect(request):
    info = identity(request)
    nodes = list(Path("/sys/class/block").glob("sd*"))
    check_unused(nodes)
    captures = capture()
    labels = check_geometry(captures)
    if request.get("fresh", False):
        require(not {"rootfs", "linux-esp"} & labels.keys(),
                "Linux partitions already exist; refusing a second installation")
    values = partition_hashes()
    assert_stock(values)
    reset.prepare(Path("/dev/disk/by-partlabel/misc").read_bytes(), keep_memtag=True)
    check_metadata_idle()
    smoke_tools()
    require(partition_hashes() == values, "Android partitions changed during RAM checks")
    compare_gpts(capture(), captures)
    return info | {"gpts": captures, "backups": values, "ram_tools_passed": True}


def approved_gpts(request):
    transaction = request["transaction"]
    writer.validate_transaction(transaction)
    require(transaction["linux_budget_gib"] == 256, "Only the tested 256 GiB profile is supported")
    expected = [transaction["after"] if c["controller_lun"] ==
                transaction["before"]["controller_lun"] else c for c in request["gpts"]]
    return expected


def quiesce():
    run("systemctl", "mask", "--runtime", "--now", "udisks2.service")
    result = subprocess.run(["systemctl", "is-active", "udisks2.service"],
                            capture_output=True, text=True)
    require(result.stdout.strip() == "inactive", "udisks2 remains active")
    run("systemctl", "stop", "display-manager.service")
    check_unused(list(Path("/sys/class/block").glob("sd*")))


def partition(request):
    identity(request)
    approved_gpts(request)
    transaction = request["transaction"]
    require(transaction["before"]["boot_id"] == request["boot_id"], "Stale partition plan")
    compare_gpts(capture(), request["gpts"])
    labels = check_geometry(request["gpts"])
    require(not {"rootfs", "linux-esp"} & labels.keys(), "Linux already installed")
    require(partition_hashes() == request["backups"], "Backup no longer matches device")
    assert_stock(request["backups"])
    misc = (BASE / "misc.img").read_bytes()
    require(digest(BASE / "misc.img") == request["backups"]["misc"]["sha256"], "Misc backup hash")
    armed = reset.prepare(misc, keep_memtag=True)
    before = transaction["before"]
    require(labels["misc"]["disk"] == before and labels["userdata"]["disk"] == before,
            "Unexpected misc/userdata LUN")
    quiesce()
    fd = os.open(before["disk_path"], os.O_RDWR | os.O_EXCL | os.O_CLOEXEC)
    try:
        require(stat.S_ISBLK(os.fstat(fd).st_mode), "Not a block device")
        size = struct.unpack("Q", fcntl.ioctl(fd, 0x80081272, b"\0" * 8))[0]
        sector = struct.unpack("I", fcntl.ioctl(fd, 0x1268, b"\0" * 4))[0]
        require(size == before["disk_bytes"] and sector == 4096, "Opened device geometry")
        writer.assert_snapshot(fd, before)
        offset = labels["misc"]["start"] * 4096
        require(os.pread(fd, len(misc), offset) == misc, "Misc changed")
        # Recovery must be durable before userdata's boundary becomes smaller.
        event("reset-request-write-start")
        require(os.pwrite(fd, armed[:4096], offset) == 4096, "Short BCB write; stop")
        os.fsync(fd)
        require(os.pread(fd, len(armed), offset) == armed, "BCB readback mismatch; stop")
        event("reset-request-verified")
        writer.apply_to_fd(fd, transaction, lambda name: event("gpt-region-verified", region=name))
    finally:
        os.close(fd)
    run("blockdev", "--rereadpt", before["disk_path"])
    run("udevadm", "settle", "--timeout=20")
    actual = capture()
    compare_gpts(actual, approved_gpts(request))
    check_geometry(actual)
    after = partition_hashes()
    require(all(after[n] == request["backups"][n] for n in LABELS if n != "misc"),
            "Unexpected change to Android partitions")
    require(after["misc"]["sha256"] == hashlib.sha256(armed).hexdigest(), "BCB changed")
    return {"partitioned": True, "reset_armed": True, "gpts": actual}


def checked_command(name, *args):
    event(name + "-start")
    with (BASE / (name + ".log")).open("x") as stream:
        result = subprocess.run([str(a) for a in args], stdout=stream, stderr=subprocess.STDOUT)
    require(result.returncode == 0, name + " failed; preserve RAM session and inspect log")
    event(name + "-passed")


def export_host_keys():
    paths = sorted(Path("/etc/ssh").glob("ssh_host_*"))
    require(any(p.name == "ssh_host_ed25519_key" for p in paths), "Missing SSH host identity")
    archive = BASE / "ssh-host-state.tar"
    with tarfile.open(archive, "x") as tar:
        for path in paths:
            require(path.is_file() and not path.is_symlink(), "Unexpected SSH key object")
            tar.add(path, arcname="etc/ssh/" + path.name, recursive=False)
    archive.chmod(0o600)
    return {"sha256": digest(archive), "bytes": archive.stat().st_size}


def check_private_tar(path):
    with tarfile.open(path) as archive:
        for member in archive:
            parts = Path(member.name).parts
            require(member.isfile() and len(parts) == 3 and parts[:2] == ("etc", "ssh")
                    and parts[2].startswith("ssh_host_"), "Invalid private host-key archive")
            require(member.uid == member.gid == 0, "Private archive ownership")
            if not member.name.endswith(".pub"):
                require(member.mode & 0o077 == 0, "Private host key permissions")


def install(request):
    identity(request)
    expected = approved_gpts(request)
    actual = capture()
    compare_gpts(actual, expected)
    labels = check_geometry(actual)
    check_unused(list(Path("/sys/class/block").glob("sd*")))
    for p in request["transaction"]["proposal"]["new_partitions"]:
        require(labels[p["label"]]["sectors"] * 4096 == p["bytes"], "Linux partition size")
    reset.prepare(Path("/dev/disk/by-partlabel/misc").read_bytes(), keep_memtag=True)
    saved = partition_hashes()
    require(all(saved[n] == request["backups"][n] for n in LABELS if n not in ("misc", "metadata")),
            "Installed Android boot images changed")
    for name in ("rootfs", "linux-esp"):
        probe = subprocess.run(["blkid", "-p", "--no-part-details", "-o", "export",
                                labels[name]["device"]], capture_output=True, text=True)
        require(probe.returncode == 2 and not probe.stdout.strip(),
                "Linux partition already has a signature; formatting cannot be retried")
    archive = BASE / "nixos-rootfs.tar.gz"
    meta = request["archive"]
    root_type = meta.get("rootfs_type", "ext4")
    require(root_type in ("ext4", "btrfs"), "Unsupported archive root filesystem")
    if root_type == "btrfs":
        require(shutil.which("mkfs.btrfs") and shutil.which("btrfs"), "Missing Btrfs maintenance tools")
    require(archive.stat().st_size == meta["archive_bytes"] and
            digest(archive) == meta["archive_sha256"], "Installation archive mismatch")
    private = BASE / "ssh-host-state.tar"
    require(digest(private) == request["host_keys_sha256"], "Host identity archive mismatch")
    check_private_tar(private)
    system = meta["system"]
    quiesce()
    rootdev, espdev = (labels[n]["device"] for n in ("rootfs", "linux-esp"))
    disk_name = Path(labels["rootfs"]["disk"]["disk_path"]).name
    require(labels["rootfs"]["disk"] == labels["linux-esp"]["disk"], "Linux partitions on different LUNs")
    for node in Path("/sys/class/block").glob("sd*"):
        if node.name not in (disk_name, Path(rootdev).name, Path(espdev).name):
            run("blockdev", "--setro", "/dev/" + node.name)
    for path in (rootdev, espdev):
        require(run("blockdev", "--getro", path) == "0", "Linux target is read-only")
    destination = BASE / "target"
    destination.mkdir(mode=0o700)
    if root_type == "btrfs":
        checked_command("format-btrfs", "mkfs.btrfs", "--nodiscard", "-L", "rootfs", rootdev)
    else:
        checked_command("format-ext4", "mkfs.ext4", "-F", "-b", "4096", "-m", "0", "-L", "rootfs",
                        "-E", "nodiscard,lazy_itable_init=0,lazy_journal_init=0", rootdev)
    checked_command("format-esp", "mkfs.fat", "-F", "32", "-S", "4096", "-n", "LINUXESP", espdev)
    run("mount", "-t", root_type, "-o", "noatime", rootdev, destination)
    try:
        checked_command("extract", "tar", "--numeric-owner", "--xattrs", "--acls",
                        "--same-owner", "--same-permissions",
                        "--exclude=./etc/y700-rootfs-contract", "--exclude=etc/y700-rootfs-contract",
                        "-C", destination, "-xzpf", archive)
        require(not (destination / "etc/y700-rootfs-contract").exists(), "Early boot contract")
        profiles = destination / "nix/var/nix/profiles"
        require(os.readlink(profiles / "system") == "system-1-link" and
                os.readlink(profiles / "system-1-link") == system, "System profile mismatch")
        require(os.readlink(destination / "init") == "/nix/var/nix/profiles/system/init", "Init link")
        require((destination / "tmp").stat().st_mode & 0o7777 == 0o1777, "Wrong /tmp mode")
        run("chroot", destination, system + "/sw/bin/test", "-x", system + "/init")
        store = "local?root=" + str(destination)
        paths = run("nix-store", "--store", store, "--query", "--requisites", system).splitlines()
        require(sorted(paths) == sorted(request["closure"]), "Store registration mismatch")
        checked_command("verify-store", "nix-store", "--store", store, "--verify", "--check-contents")
        checked_command("restore-host-keys", "tar", "--numeric-owner", "--same-owner",
                        "--same-permissions", "-C", destination, "-xpf", private)
        marker = destination / "var/lib/y700-install"
        marker.mkdir(parents=True)
        write_json(marker / "initial.json", {"schema": 1, "system": system,
                   "rootfs_archive_sha256": meta["archive_sha256"], "linux_budget_gib": 256})
        run("sync", "-f", destination)
    finally:
        run("umount", destination)
    if root_type == "btrfs":
        checked_command("check-btrfs", "btrfs", "check", "--readonly", rootdev)
    else:
        checked_command("check-ext4", "e2fsck", "-f", "-n", rootdev)
    checked_command("check-esp", "fsck.fat", "-n", espdev)
    compare_gpts(capture(), expected)
    require(partition_hashes() == saved, "Android partition changed during installation")
    run("mount", "-t", root_type, "-o", "noatime", rootdev, destination)
    contract = destination / "etc/y700-rootfs-contract"
    try:
        with contract.open("x") as stream:
            stream.write("tb322fc-rootfs-v1\n")
            stream.flush()
            os.fsync(stream.fileno())
        run("sync", "-f", destination)
    except BaseException:
        contract.unlink(missing_ok=True)
        run("sync", "-f", destination)
        raise
    finally:
        run("umount", destination)
    return {"installed": True, "registered_paths": len(paths), "system": system,
            "gpts": expected, "host_keys_restored": True, "root_unmounted": True}


def verify(request):
    result = identity(request, persistent=True)
    compare_gpts(capture(), approved_gpts(request))
    rootdev = Path("/dev/disk/by-partlabel/rootfs").resolve(strict=True)
    root = json.loads(run("findmnt", "-J", "-o", "SOURCE,FSTYPE,OPTIONS", "/"))["filesystems"][0]
    require(root["source"].split("[", 1)[0] == str(rootdev) and
            root["fstype"] in ("ext4", "btrfs") and
            "rw" in root["options"].split(","), "Not the installed writable root")
    require(str(Path("/nix/var/nix/profiles/system").resolve()) == request["system"], "Profile differs")
    require(not list(Path("/sys/class/block").glob("nbd*")), "NBD remains present")
    require(not any(line.split()[2] == "overlay" for line in Path("/proc/mounts").read_text().splitlines()),
            "Overlay remains present")
    require(not run("systemctl", "--failed", "--no-legend", "--no-pager"), "Failed system units")
    disk = (Path("/sys/class/block") / rootdev.name).resolve().parent
    for node in Path("/sys/class/block").glob("sd*"):
        expected = "0" if node.name in (rootdev.name, disk.name) else "1"
        require(run("blockdev", "--getro", "/dev/" + node.name) == expected, "Partition protection")
    for unit in ("display-manager", "sshd", "y700-power-key", "y700-local-root-prepare-shutdown"):
        require(run("systemctl", "is-active", unit) == "active", "Inactive service: " + unit)
    result["root"] = root
    if request.get("marker"):
        require(json.loads(Path("/var/lib/y700-install/persistence-test.json").read_text()) ==
                request["marker"], "Persistence marker differs")
        shadow = next(line.split(":")[1] for line in Path("/etc/shadow").read_text().splitlines()
                      if line.startswith("y700:"))
        require(hashlib.sha256(shadow.encode()).hexdigest() == request["password_fingerprint"],
                "Desktop password did not persist")
        require(result["boot_id"] != request["marker"]["first_boot_id"], "No intervening reboot")
        result["persistence_verified"] = True
    return result


def initialize(request):
    result = verify(request)
    shadow = next(line.split(":")[1] for line in Path("/etc/shadow").read_text().splitlines()
                  if line.startswith("y700:"))
    require(shadow.startswith(("!", "*")), "Password already set; preserve owner changes")
    password_hash = request["password_hash"]
    require(password_hash.startswith("$6$") and "\n" not in password_hash, "Password hash format")
    run("chpasswd", "-e", input="y700:" + password_hash + "\n")
    shadow = next(line.split(":")[1] for line in Path("/etc/shadow").read_text().splitlines()
                  if line.startswith("y700:"))
    require(shadow == password_hash, "Password initialization failed")
    write_json("/var/lib/y700-install/persistence-test.json", request["new_marker"])
    run("sync", "-f", "/")
    return result | {"initialized": True,
                     "password_fingerprint": hashlib.sha256(shadow.encode()).hexdigest()}


def reboot(request):
    persistent = request.get("persistent", False)
    identity(request, persistent=persistent)
    misc = Path("/dev/disk/by-partlabel/misc").read_bytes()
    if request.get("reset_armed"):
        expected = reset.prepare((BASE / "misc.img").read_bytes(), keep_memtag=True)
        require(misc == expected, "Expected reset request is absent")
    else:
        reset.prepare(misc, keep_memtag=True)
    if not persistent:
        check_unused(list(Path("/sys/class/block").glob("sd*")))
        unit = "y700-usb-nbd-prepare-shutdown"
    else:
        unit = "y700-local-root-prepare-shutdown"
    require(run("systemctl", "is-active", unit) == "active", "Shutdown preparation not active")
    require(Path("/run/initramfs/shutdown").is_file(), "Missing shutdown ramfs")
    run("sync")
    event("reboot-requesting")
    run("systemctl", "reboot")
    event("reboot-accepted")
    return {"requested": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "partition", "keys", "install",
                                          "verify", "initialize", "reboot"])
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    request = json.loads(args.request.read_text())
    require(str(BASE).startswith("/run/y700-installer-"), "Bundle must reside in maintenance RAM")
    require(run("findmnt", "-n", "-o", "FSTYPE", "-T", BASE) == "tmpfs", "Bundle is not in tmpfs")
    with Path("/run/y700-installer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "keys":
            identity(request)
            result = export_host_keys()
        else:
            if args.action in ("partition", "install", "initialize"):
                write_json(BASE / (args.action + "-attempt.json"), {"started": time.time()})
            result = globals()[args.action](request)
        write_json(BASE / (args.action + "-result.json"), result)
        event("complete", action=args.action, result=result)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        event("stopped", error=str(error), instruction="Keep the RAM session alive; do not retry writes.")
        sys.exit(1)
