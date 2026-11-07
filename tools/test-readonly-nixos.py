#!/usr/bin/env python3
"""Compare readonly handoff into real NixOS userspace on synthetic QEMU disks."""
import argparse
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import shutil
import subprocess
import time


PROJECT = Path(__file__).resolve().parents[1]
FAKE_SYSTEM = "/nix/store/" + "0" * 32 + "-nixos-system-handoff-test"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--baseline-init", type=Path, required=True)
    parser.add_argument("--init", type=Path,
                        default=PROJECT / "vendor/tb322fc-linux/initramfs/init")
    parser.add_argument("--tools", type=Path, default=PROJECT / "result-efi-lab-tools")
    parser.add_argument("--busybox", type=Path, required=True)
    parser.add_argument("--gen-init-cpio", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists() or output.is_symlink():
        parser.error("output must be new")
    system, tools, busybox, gen_cpio, baseline, candidate = (
        p.resolve(strict=True) for p in (
            args.system, args.tools, args.busybox, args.gen_init_cpio,
            args.baseline_init, args.init,
        )
    )
    if system.parent != Path("/nix/store") or not (system / "init").is_file():
        parser.error("system must be an existing immutable NixOS store output")
    for path in (output, system, tools, busybox, gen_cpio, baseline, candidate):
        if any(c.isspace() for c in str(path)):
            parser.error("fixture paths must not contain whitespace")
    output.mkdir(parents=True)
    helper_path = PROJECT / "tools/test-persistent-handoff.py"
    spec = importlib.util.spec_from_file_location("handoff_lab", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    modules = tools / "kernel-modules"
    version = next((modules / "lib/modules").iterdir()).name
    needed = []
    for name in ("virtio_mmio", "virtio_scsi", "sd_mod", "ext4", "overlay",
                 "9p", "9pnet_virtio"):
        text = subprocess.check_output(
            ["modprobe", "-d", str(modules), "-S", version, "--show-depends", name],
            text=True,
        )
        for line in text.splitlines():
            if line.startswith("insmod "):
                source = Path(line.split()[1])
                if source not in needed:
                    needed.append(source)
    stage = output / "stage"
    for name in ("bin", "dev", "proc", "sys", "run", "etc", "var", "tmp",
                 "nix/var/nix/profiles", FAKE_SYSTEM.removeprefix("/")):
        (stage / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(busybox, stage / "bin/busybox")
    (stage / "bin/sh").symlink_to("busybox")
    (stage / "etc/y700-rootfs-contract").write_text("tb322fc-rootfs-v1\n")
    shutil.copyfile(system / "etc/fstab", stage / "etc/fstab")
    (stage / "etc/mtab").symlink_to("/proc/self/mounts")
    profiles = stage / "nix/var/nix/profiles"
    (profiles / "system").symlink_to("system-1-link")
    (profiles / "system-1-link").symlink_to(FAKE_SYSTEM)
    stub = stage / FAKE_SYSTEM.removeprefix("/") / "init"
    stub.write_text("""#!/bin/sh
BB=/bin/busybox
fail() { echo "READONLY_NIXOS_FAIL=$*"; $BB poweroff -f; while :; do $BB sleep 1; done; }
for option in $($BB cat /proc/cmdline); do
    case "$option" in
        y700.lab-expect=corrected)
            for alias in fd stdin stdout stderr; do
                [ -L "/dev/$alias" ] || fail early-devfs-alias
            done
            echo READONLY_NIXOS_DEVFS_ALIASES=pass
            ;;
    esac
done
$BB mount -t 9p -o trans=virtio,version=9p2000.L,ro store /nix/store || fail store
$BB mkdir -p /run/systemd/system/sysinit.target.wants
$BB cat > /run/systemd/system/y700-readonly-lab.service <<'UNIT'
[Unit]
Description=Readonly NixOS remount laboratory
DefaultDependencies=no
Wants=systemd-remount-fs.service
After=systemd-remount-fs.service
Before=basic.target
[Service]
Type=oneshot
ExecStart=/bin/busybox sh /lab-report
StandardOutput=tty
StandardError=tty
TTYPath=/dev/console
UNIT
$BB ln -s ../y700-readonly-lab.service /run/systemd/system/sysinit.target.wants/
exec """ + str(system) + """/init
fail stage2-returned
""")
    stub.chmod(0o755)
    (stage / "lab-report").write_text("""#!/bin/sh
BB=/bin/busybox
SYSTEM=""" + str(system) + """
CTL=$SYSTEM/sw/bin/systemctl
fail() { echo "READONLY_NIXOS_FAIL=$*"; $BB poweroff -f; while :; do $BB sleep 1; done; }
expected=
for option in $($BB cat /proc/cmdline); do
    case "$option" in y700.lab-expect=*) expected=${option#*=};; esac
done
[ "$($BB readlink /run/booted-system)" = "$SYSTEM" ] || fail booted-system
[ "$($BB readlink /run/current-system)" = "$SYSTEM" ] || fail current-system
state=$($CTL show --value --property=ActiveState systemd-remount-fs.service) || fail service-query
echo "READONLY_NIXOS_REMOUNT_STATE=$state"
$CTL show --property=Environment,Result systemd-remount-fs.service
$BB cat /run/systemd/generator/-.mount || fail root-generator
case "$expected" in
    control)
        [ "$state" = failed ] || fail expected-control-failure
        $BB grep -qx 'Type=ext4' /run/systemd/generator/-.mount || fail control-root-unit
        ;;
    corrected)
        [ "$state" = active ] || fail remount-service
        for line in 'What=overlay' 'Type=overlay' 'Options=rw,noatime' \
            'SourcePath=/run/y700-root/fstab'; do
            $BB grep -qx "$line" /run/systemd/generator/-.mount || fail root-unit
        done
        ;;
    *) fail missing-expectation;;
esac
$BB grep -Eq ' / overlay rw(,| )' /proc/mounts || fail root-mount
$BB grep -Eq ' /run/y700-root/lower ext4 ro,([^ ]*,)?(noload|norecovery)(,| )' /proc/mounts ||
    fail lower-mount
$BB grep -Eq ' /run/y700-root/overlay tmpfs rw,[^ ]*size=2097152k(,| )' /proc/mounts ||
    fail upper-size
count=0
for device in /dev/sd*; do
    [ -b "$device" ] || continue
    [ "$($BB blockdev --getro "$device")" = 1 ] || fail writable-disk
    count=$((count+1))
done
[ "$count" = 18 ] || fail block-inventory
$BB cat /proc/mounts
$BB cat /etc/fstab
echo "READONLY_NIXOS_PASS=$expected"
$BB poweroff -f
while :; do $BB sleep 1; done
""")
    fs = output / "rootfs.ext4"
    with fs.open("xb") as stream:
        stream.truncate(128 << 20)
    run("mke2fs", "-q", "-t", "ext4", "-b", "4096", "-d", stage, fs)
    disks = [helper.disk_image(output, "root.img", "rootfs", fs)]
    disks += [helper.disk_image(output, f"other-{n}.img", f"android-{n}")
              for n in range(5)]
    initial_hashes = {p.name: sha256(p) for p in disks}
    results = []
    for label, init in (("control", baseline), ("corrected", candidate)):
        case = output / label
        case.mkdir()
        wrapper = case / "init"
        wrapper.write_text("#!/bin/sh\nset -eu\n" + "\n".join(
            f"/bin/busybox insmod /modules/{n}.ko" for n in range(len(needed))
        ) + "\nexec /persistent-init\n")
        marker = case / "readonly"
        marker.write_text("readonly-overlay\n")
        listing = [
            *[f"dir /{d} 0755 0 0" for d in
              ("bin", "dev", "proc", "sys", "run", "etc", "modules", "lib", "lib/firmware")],
            "nod /dev/console 0600 0 0 c 5 1",
            f"file /bin/busybox {busybox} 0755 0 0",
            "slink /bin/sh busybox 0755 0 0",
            f"file /init {wrapper} 0755 0 0",
            f"file /persistent-init {init} 0755 0 0",
            f"file /etc/y700-root-readonly {marker} 0444 0 0",
        ]
        for n, source in enumerate(needed):
            target = case / f"module-{n}.ko"
            target.write_bytes(lzma.decompress(source.read_bytes())
                               if source.suffix == ".xz" else source.read_bytes())
            listing.append(f"file /modules/{n}.ko {target} 0444 0 0")
        (case / "initramfs.list").write_text("\n".join(listing) + "\n")
        cpio = case / "initramfs.cpio"
        with cpio.open("xb") as stream:
            run(gen_cpio, "-t", "0", case / "initramfs.list", stdout=stream)
        log = case / "serial.log"
        command = [
            tools / "qemu/bin/qemu-system-aarch64",
            "-machine", "virt,gic-version=3", "-cpu", "cortex-a72",
            "-accel", "tcg", "-m", "1536", "-smp", "2", "-display", "none",
            "-monitor", "none", "-serial", f"file:{log}", "-nic", "none", "-no-reboot",
            "-kernel", tools / "kernel/Image", "-initrd", cpio,
            "-append", "console=ttyAMA0 rdinit=/init panic=5 root=PARTLABEL=rootfs "
                       f"systemd.unit=multi-user.target y700.lab-expect={label}",
            "-virtfs", "local,path=/nix/store,mount_tag=store,security_model=none,readonly=on",
            "-device", "virtio-scsi-device,id=scsi", "-device", "virtio-rng-device",
        ]
        for n, disk in enumerate(disks):
            command += [
                "-drive", f"if=none,id=d{n},format=raw,file={disk}",
                "-device", f"scsi-hd,drive=d{n},bus=scsi.0,scsi-id=0,lun={n},"
                           "logical_block_size=4096,physical_block_size=4096",
            ]
        (case / "command.json").write_text(json.dumps(list(map(str, command)), indent=2) + "\n")
        start = time.monotonic()
        with (case / "qemu.log").open("xb") as stream:
            result = run(*command, stdin=subprocess.DEVNULL, stdout=stream,
                         stderr=stream, timeout=100)
        text = log.read_text(errors="replace")
        passed = (result.returncode == 0 and f"READONLY_NIXOS_PASS={label}" in text
                  and "READONLY_NIXOS_FAIL=" not in text)
        if label == "corrected":
            passed = (passed and "READONLY_NIXOS_DEVFS_ALIASES=pass" in text
                      and "/dev/fd/63: No such file or directory" not in text
                      and "Activation script snippet '" not in text)
        unchanged = initial_hashes == {p.name: sha256(p) for p in disks}
        results.append({
            "case": label, "passed": passed, "all_disks_unchanged": unchanged,
            "seconds": round(time.monotonic() - start, 3),
            "init_sha256": sha256(init), "initramfs_sha256": sha256(cpio),
            "serial_sha256": sha256(log),
        })
        (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        if not passed or not unchanged:
            raise RuntimeError(f"{label} failed; inspect {case}")
        print(f"{label}: passed; all six synthetic disks unchanged", flush=True)
    report = {
        "scope": "QEMU readonly remount contract with actual NixOS stage2 and systemd",
        "limits": "Not full boot, GNOME, target hardware or tablet filesystem validation.",
        "system": str(system), "system_init_sha256": sha256(system / "init"),
        "system_activate_sha256": sha256(system / "activate"),
        "fstab_sha256": sha256(system / "etc/fstab"),
        "kernel_sha256": sha256(tools / "kernel/Image"),
        "qemu_sha256": sha256(tools / "qemu/bin/qemu-system-aarch64"),
        "busybox_sha256": sha256(busybox), "gen_init_cpio_sha256": sha256(gen_cpio),
        "fixture_helper_sha256": sha256(helper_path),
        "initial_disk_hashes": initial_hashes, "cases": results,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Report: {output / 'report.json'}")


if __name__ == "__main__":
    main()
