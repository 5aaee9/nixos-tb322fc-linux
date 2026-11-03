#!/usr/bin/env python3
"""Exercise the real local-root initramfs with six QEMU SCSI disks, never a tablet."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import time

PROJECT = Path(__file__).resolve().parents[1]
VENDOR = PROJECT / "vendor/tb322fc-linux"
SYSTEM = "/nix/store/" + "0" * 32 + "-nixos-system-handoff-test"


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def disk_image(output, name, label, rootfs=None):
    disk = output / name
    with disk.open("xb") as stream:
        stream.truncate(160 << 20)
    # A regular host file with 4 KiB sectors, never a block-device path.
    layout = (f"label: gpt\nunit: sectors\n\n"
              f"start=256,size=32768,type=L,name={label}\n"
              "start=33024,size=512,type=L,name=android-sentinel\n")
    run("sfdisk", "--sector-size", "4096", "--no-reread", "--no-tell-kernel",
        disk, input=layout, text=True, stdout=subprocess.DEVNULL)
    with disk.open("r+b") as stream:
        if rootfs:
            stream.seek(1 << 20)
            with rootfs.open("rb") as source:
                shutil.copyfileobj(source, stream)
        stream.seek(33024 * 4096)
        stream.write(b"ANDROID-MUST-STAY-UNCHANGED\n" * 100)
    return disk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tools", type=Path, default=PROJECT / "result-efi-lab-tools")
    parser.add_argument("--busybox", type=Path, default=PROJECT / "result-busybox/bin/busybox")
    parser.add_argument("--gen-init-cpio", type=Path, default=PROJECT / "result-gen-init-cpio/bin/gen_init_cpio")
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists():
        parser.error("output must be new")
    output.mkdir(parents=True)
    tools = args.tools.resolve(strict=True)
    busybox = args.busybox.resolve(strict=True)
    gen_cpio = args.gen_init_cpio.resolve(strict=True)
    init = VENDOR / "initramfs/init"
    kernel = tools / "kernel/Image"
    modules = tools / "kernel-modules"
    version = next((modules / "lib/modules").iterdir()).name
    needed = []
    for name in ("virtio_mmio", "virtio_scsi", "sd_mod", "ext4"):
        result = subprocess.check_output(
            ["modprobe", "-d", str(modules), "-S", version, "--show-depends", name],
            text=True)
        for line in result.splitlines():
            if line.startswith("insmod "):
                path = Path(line.split()[1])
                if path not in needed:
                    needed.append(path)
    wrapper = output / "init"
    wrapper.write_text("#!/bin/sh\nset -eu\n" +
                       "\n".join(f"/bin/busybox insmod /modules/{n}.ko" for n in range(len(needed))) +
                       "\nexec /persistent-init\n")
    listing = [
        "dir /bin 0755 0 0", "dir /dev 0755 0 0", "dir /proc 0755 0 0",
        "dir /sys 0755 0 0", "dir /run 0755 0 0", "dir /etc 0755 0 0",
        "dir /lib 0755 0 0", "dir /lib/firmware 0755 0 0",
        "dir /modules 0755 0 0", "nod /dev/console 0600 0 0 c 5 1",
        f"file /bin/busybox {busybox} 0755 0 0", "slink /bin/sh busybox 0755 0 0",
        f"file /init {wrapper} 0755 0 0", f"file /persistent-init {init} 0755 0 0",
    ]
    for n, source in enumerate(needed):
        target = output / f"module-{n}.ko"
        target.write_bytes(lzma.decompress(source.read_bytes()) if source.suffix == ".xz"
                           else source.read_bytes())
        listing.append(f"file /modules/{n}.ko {target} 0444 0 0")
    (output / "initramfs.list").write_text("\n".join(listing) + "\n")
    cpio = output / "initramfs.cpio"
    with cpio.open("xb") as stream:
        run(gen_cpio, "-t", "0", output / "initramfs.list", stdout=stream)

    stage = output / "stage"
    for directory in ("bin", "dev", "proc", "sys", "run", "etc", "var",
                      "nix/var/nix/profiles", SYSTEM.removeprefix("/")):
        (stage / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2(busybox, stage / "bin/busybox")
    (stage / "bin/sh").symlink_to("busybox")
    (stage / "etc/y700-rootfs-contract").write_text("tb322fc-rootfs-v1\n")
    profiles = stage / "nix/var/nix/profiles"
    (profiles / "system").symlink_to("system-1-link")
    (profiles / "system-1-link").symlink_to(SYSTEM)
    stage2 = stage / SYSTEM.removeprefix("/") / "init"
    stage2.write_text("""#!/bin/sh
BB=/bin/busybox
fail() { echo "PERSIST_TEST_FAIL=$*"; $BB poweroff -f; while :; do $BB sleep 1; done; }
test "$($BB stat -f -c %T /)" = ext2/ext3 || fail root-filesystem
for device in /dev/sda2 /dev/sdb /dev/sdc /dev/sdd /dev/sde /dev/sdf; do
    test "$($BB blockdev --getro "$device")" = 1 || fail android-write-protection
done
if test -e /var/persistence-marker; then
    test "$($BB cat /var/persistence-marker)" = first-boot || fail marker
    echo PERSIST_TEST_RETAINED
else
    echo first-boot > /var/persistence-marker
    echo PERSIST_TEST_CREATED
fi
$BB sync
$BB mount -o remount,ro / || fail clean-remount
echo PERSIST_TEST_PASS
$BB poweroff -f
while :; do $BB sleep 1; done
""")
    stage2.chmod(0o755)
    fs = output / "rootfs.ext4"
    with fs.open("xb") as stream:
        stream.truncate(128 << 20)
    # These simulated disks expose 4 KiB sectors; small-image defaults use 1 KiB.
    run("mke2fs", "-q", "-F", "-t", "ext4", "-b", "4096", "-d", stage, fs)
    root = disk_image(output, "data.img", "rootfs", fs)
    other = [disk_image(output, f"other-{i}.img", f"android-{i}") for i in range(5)]
    initial_hashes = {p.name: sha256(p) for p in other}
    with root.open("rb") as stream:
        prefix = hashlib.sha256(stream.read(1 << 20)).hexdigest()
        stream.seek(33024 * 4096)
        suffix = hashlib.sha256(stream.read()).hexdigest()
    records = []

    def boot(label, expected, disks):
        log = output / f"{label}.log"
        command = [tools / "qemu/bin/qemu-system-aarch64",
                   "-machine", "virt,gic-version=3", "-cpu", "cortex-a72",
                   "-accel", "tcg", "-m", "1024", "-smp", "2", "-display", "none",
                   "-monitor", "none", "-serial", f"file:{log}", "-nic", "none", "-no-reboot",
                   "-kernel", kernel, "-initrd", cpio,
                   "-append", "console=ttyAMA0 rdinit=/init panic=5 root=PARTLABEL=rootfs",
                   "-device", "virtio-scsi-device,id=scsi"]
        for i, disk in enumerate(disks):
            command += ["-drive", f"if=none,id=d{i},format=raw,file={disk}",
                        "-device", f"scsi-hd,drive=d{i},bus=scsi.0,scsi-id=0,lun={i},"
                                   "logical_block_size=4096,physical_block_size=4096"]
        start = time.monotonic()
        with (output / f"{label}-qemu.log").open("wb") as errors:
            result = subprocess.run([str(x) for x in command], timeout=110,
                                    stdin=subprocess.DEVNULL, stdout=errors, stderr=errors)
        text = log.read_text(errors="replace")
        passed = result.returncode == 0 and expected in text and "PERSIST_TEST_FAIL" not in text
        records.append(dict(test=label, passed=passed, seconds=round(time.monotonic() - start, 3)))
        if not passed:
            raise RuntimeError(f"{label} failed; inspect {log}")
        print(f"{label}: passed", flush=True)

    boot("first-boot", "PERSIST_TEST_CREATED", [root, *other])
    boot("second-boot", "PERSIST_TEST_RETAINED", [root, *other])
    after_success = sha256(root)
    duplicate = disk_image(output, "duplicate.img", "rootfs", fs)
    duplicate_hash = sha256(duplicate)
    boot("duplicate-rejected", "Rootfs handoff failed: ambiguous rootfs partition",
         [root, duplicate, *other[1:]])
    if after_success != sha256(root) or duplicate_hash != sha256(duplicate):
        raise RuntimeError("ambiguous-root rejection modified a disk")
    if initial_hashes != {p.name: sha256(p) for p in other}:
        raise RuntimeError("an Android sentinel disk changed")
    # A single label match is insufficient: malformed installation metadata
    # must be rejected before ext4 journal replay or superblock updates.
    for name, expected in (("missing-contract", "missing install contract"),
                           ("invalid-profile", "profile name")):
        if name == "missing-contract":
            (stage / "etc/y700-rootfs-contract").unlink()
        else:
            (stage / "etc/y700-rootfs-contract").write_text("tb322fc-rootfs-v1\n")
            (profiles / "system").unlink()
            (profiles / "system").symlink_to("../../../../etc")
        badfs = output / f"{name}.ext4"
        with badfs.open("xb") as stream:
            stream.truncate(128 << 20)
        run("mke2fs", "-q", "-F", "-t", "ext4", "-b", "4096", "-d", stage, badfs)
        bad_disk = disk_image(output, f"{name}.img", "rootfs", badfs)
        before = sha256(bad_disk)
        boot(name, f"Rootfs handoff failed: {expected}", [bad_disk, *other])
        if before != sha256(bad_disk):
            raise RuntimeError(f"{name} refusal modified the disk")
    if initial_hashes != {p.name: sha256(p) for p in other}:
        raise RuntimeError("an Android sentinel disk changed during refusal tests")
    with root.open("rb") as stream:
        assert hashlib.sha256(stream.read(1 << 20)).hexdigest() == prefix
        stream.seek(33024 * 4096)
        assert hashlib.sha256(stream.read()).hexdigest() == suffix
    with root.open("rb") as source, (output / "rootfs-after.ext4").open("xb") as target:
        source.seek(1 << 20)
        for _ in range(128):
            target.write(source.read(1 << 20))
    run("e2fsck", "-fn", output / "rootfs-after.ext4")
    metadata = dict(scope="QEMU only; not TB322FC/UFS/NixOS hardware acceptance",
                    tests=records, init_sha256=sha256(init), kernel_sha256=sha256(kernel),
                    busybox_sha256=sha256(busybox), gen_init_cpio_sha256=sha256(gen_cpio),
                    initramfs_sha256=sha256(cpio), android_sentinels_unchanged=True)
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
