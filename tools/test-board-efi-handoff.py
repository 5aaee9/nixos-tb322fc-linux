#!/usr/bin/env python3
"""Test the real board EFI kernel/common init with synthetic stage2 on host QEMU."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

PROJECT = Path(__file__).resolve().parents[1]
VENDOR = PROJECT / "vendor/tb322fc-linux"
GUID = "4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"
SYSTEMS = {n: f"/nix/store/{str(n) * 32}-nixos-system-efi-lab-{n}" for n in (1, 2, 3)}


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROJECT / "tools" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


handoff = module("persistent_lab", "test-persistent-handoff.py")
generation = module("efi_bundle", "build-efi-generation.py")
sha = generation.sha


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, **kwargs)


def initrd(output, number, busybox, gen_cpio):
    listing = [
        "dir /bin 0755 0 0", "dir /dev 0755 0 0", "dir /proc 0755 0 0",
        "dir /sys 0755 0 0", "dir /run 0755 0 0", "dir /etc 0755 0 0",
        "dir /lib 0755 0 0", "dir /lib/firmware 0755 0 0",
        "nod /dev/console 0600 0 0 c 5 1",
        f"file /bin/busybox {busybox} 0755 0 0", "slink /bin/sh busybox 0755 0 0",
        f"file /init {VENDOR / 'initramfs/init'} 0755 0 0",
    ]
    system, entry = output / f"system-{number}", output / f"generation-{number}"
    system.write_text(SYSTEMS[number] + "\n")
    entry.write_text(str(number) + "\n")
    listing += [f"file /etc/y700-efi-system {system} 0444 0 0",
                f"file /etc/y700-efi-generation {entry} 0444 0 0"]
    manifest = output / f"initramfs-{number}.list"
    manifest.write_text("\n".join(listing) + "\n")
    path = output / f"initrd-{number}.cpio"
    with path.open("xb") as stream:
        run([gen_cpio, "-t", "0", manifest], stdout=stream)
    return path


def stage2(number):
    return f"""#!/bin/sh
BB=/bin/busybox
fail() {{ echo "BOARD_EFI_FAIL=$*"; $BB poweroff -f; while :; do $BB sleep 1; done; }}
test "$($BB stat -f -c %T /)" = ext2/ext3 || fail not-ext4
root_device=$($BB awk '$2 == "/" {{print $1}}' /proc/mounts)
test -b "$root_device" || fail missing-root-device
root_disk=$($BB dirname "$($BB readlink -f "/sys/class/block/${{root_device##*/}}")")
for node in /sys/class/block/sd*; do
    device=/dev/${{node##*/}}
    test "$device" = "$root_device" && continue
    test "$device" = "/dev/${{root_disk##*/}}" && continue
    test "$($BB blockdev --getro "$device")" = 1 || fail android-write-protection
done
$BB mount -t efivarfs efivarfs /sys/firmware/efi/efivars || fail efivarfs
efivars=/sys/firmware/efi/efivars
entry=$($BB dd if="$efivars/LoaderEntrySelected-{GUID}" bs=1 skip=4 2>/dev/null | $BB tr -d '\\000')
test "$entry" = nixos-generation-{number}.conf || fail selected-entry
loader=$($BB dd if="$efivars/LoaderInfo-{GUID}" bs=1 skip=4 2>/dev/null | $BB tr -d '\\000')
case "$loader" in systemd-boot*) ;; *) fail wrong-loader ;; esac
test ! -e "$efivars/LoaderEntryOneShot-{GUID}" || fail oneshot-not-consumed
echo BOARD_EFI_SELECTED={number}
state=$($BB cat /var/efi-test-state 2>/dev/null || true)
case "{number}:$state" in
    2:)
        $BB cat /etc/oneshot-gen1 > "$efivars/LoaderEntryOneShot-{GUID}" || fail set-oneshot
        echo requested-old > /var/efi-test-state
        echo BOARD_EFI_ONESHOT_REQUESTED
        action=reboot
        ;;
    1:requested-old)
        test "$($BB readlink /nix/var/nix/profiles/system)" = system-2-link || fail default-profile
        echo selected-old > /var/efi-test-state
        echo BOARD_EFI_OLD_GENERATION_WITH_NEW_DEFAULT
        action=reboot
        ;;
    2:selected-old)
        echo completed > /var/efi-test-state
        echo BOARD_EFI_DEFAULT_RESTORED
        action=poweroff
        ;;
    *) fail unexpected-order ;;
esac
$BB sync
$BB mount -o remount,ro / || fail clean-remount
echo BOARD_EFI_STAGE2_PASS={number}
$BB "$action" -f
while :; do $BB sleep 1; done
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--tools", type=Path, default=PROJECT / "result-efi-lab-tools")
    parser.add_argument("--busybox", type=Path, default=PROJECT / "result-busybox/bin/busybox")
    parser.add_argument("--gen-init-cpio", type=Path, default=PROJECT / "result-gen-init-cpio/bin/gen_init_cpio")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--generation", action="append", type=Path,
                        help="Use the actual gzip initrds of verified generations 1 and 2")
    args = parser.parse_args()
    output, tools = args.out.absolute(), args.tools.resolve(strict=True)
    if output.exists():
        parser.error("output must be a new directory")
    kernel_dir = args.kernel.resolve(strict=True)
    generation.verify_kernel(kernel_dir)
    bundles = {}
    if args.generation:
        assembler = module("efi_esp_lab", "build-efi-esp.py")
        bundles = assembler.select_generations(
            [p.resolve(strict=True) for p in args.generation], 2)
        generation.require(set(bundles) == {1, 2}, "This lab requires generations 1 and 2")
        for number, (_, meta) in bundles.items():
            generation.require(meta["files"]["linux.efi"] == sha(kernel_dir / "Image"),
                               "Lab kernel differs from the production bundle")
            SYSTEMS[number] = meta["system"]
    output.mkdir(parents=True)
    kernel = kernel_dir / "Image"
    busybox = args.busybox.resolve(strict=True)
    gen_cpio = args.gen_init_cpio.resolve(strict=True)
    loader = tools / "systemd/lib/systemd/boot/efi/systemd-bootaa64.efi"
    firmware = next((tools / "firmware").rglob("AAVMF_CODE.fd"))
    var_template = next((tools / "firmware").rglob("AAVMF_VARS.fd"))
    inputs = {str(p): sha(p) for p in (kernel, busybox, gen_cpio, loader, firmware, var_template,
                                     VENDOR / "initramfs/init")}
    evidence = {
        "scope": "QEMU only: board EFI kernel + real common init + synthetic stage2, no tablet/NixOS runtime acceptance",
        "devicetree": "QEMU firmware platform tree, not elden.dtb",
        "inputs": inputs, "runs": [],
    }
    report = output / "metadata.json"
    report.write_text(json.dumps(evidence, indent=2) + "\n")
    stage = output / "stage"
    for directory in ("bin", "dev", "proc", "sys", "run", "etc", "var", "nix/var/nix/profiles"):
        (stage / directory).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(busybox, stage / "bin/busybox")
    (stage / "bin/busybox").chmod(0o755)
    (stage / "bin/sh").symlink_to("busybox")
    (stage / "etc/y700-rootfs-contract").write_text("tb322fc-rootfs-v1\n")
    # EFI variables carry a 32-bit attributes word followed by UTF-16 data.
    (stage / "etc/oneshot-gen1").write_bytes(
        b"\x07\0\0\0" + "nixos-generation-1.conf\0".encode("utf-16-le"))
    for number in (1, 2):
        target = stage / SYSTEMS[number].lstrip("/")
        target.mkdir(parents=True)
        (target / "init").write_text(stage2(number))
        (target / "init").chmod(0o755)
        (stage / f"nix/var/nix/profiles/system-{number}-link").symlink_to(SYSTEMS[number])
    (stage / "nix/var/nix/profiles/system").symlink_to("system-2-link")
    fs = output / "rootfs.ext4"
    with fs.open("xb") as stream:
        stream.truncate(128 << 20)
    # Match the simulated disks' 4 KiB logical sectors explicitly.
    run(["mke2fs", "-q", "-F", "-t", "ext4", "-b", "4096", "-d", stage, fs])
    root = handoff.disk_image(output, "data.img", "rootfs", fs)
    other = [handoff.disk_image(output, f"other-{n}.img", f"android-{n}") for n in range(5)]
    protected = {p.name: sha(p) for p in other}

    def root_protected():
        with root.open("rb") as stream:
            prefix = hashlib.sha256(stream.read(1 << 20)).hexdigest()
            stream.seek(33024 * 4096)
            return prefix, hashlib.sha256(stream.read()).hexdigest()

    boundaries = root_protected()
    initrds = {n: bundles[n][0] / "initrd.gz" if n in bundles else initrd(output, n, busybox, gen_cpio)
               for n in (1, 2, 3)}
    evidence["initrds"] = {
        n: {"sha256": sha(path), "source": str(path),
            "kind": "production gzip initrd" if n in bundles else "synthetic test cpio"}
        for n, path in initrds.items()
    }
    evidence["stage2"] = "synthetic acceptance scripts at selected system paths, not NixOS activation"
    evidence["command_line"] = "QEMU console and platform; USB diagnostics disabled"
    mtools = tools / "mtools/bin"
    env = os.environ | {"MTOOLSRC": "/dev/null"}
    esp = output / "esp-base.img"
    with esp.open("xb") as stream:
        stream.truncate(1 << 30)
    run([tools / "dosfstools/bin/mkfs.fat", "--invariant", "-F", "32",
         "-S", "4096", "-s", "1", esp], stdout=subprocess.DEVNULL)
    run([mtools / "mmd", "-i", esp, "::/EFI", "::/EFI/BOOT", "::/EFI/Linux",
         "::/loader", "::/loader/entries"], env=env)
    run([mtools / "mcopy", "-i", esp, loader, "::/EFI/BOOT/BOOTAA64.EFI"], env=env)
    run([mtools / "mcopy", "-i", esp, kernel, "::/EFI/Linux/linux.efi"], env=env)
    for number, path in initrds.items():
        run([mtools / "mcopy", "-i", esp, path, f"::/EFI/Linux/initrd-{number}.cpio"], env=env)
    config = output / "loader.conf"
    config.write_text("default nixos-generation-2.conf\ntimeout 0\neditor no\nauto-entries no\nauto-firmware no\n")
    run([mtools / "mcopy", "-i", esp, config, "::/loader/loader.conf"], env=env)

    def entry(disk, number, selected=None, missing=False):
        path = output / f"entry-{number}.conf"
        selected = number if selected is None else selected
        options = (f"console=ttyAMA0 acpi=off rdinit=/init panic=5 root=PARTLABEL=rootfs "
                   f"y700.system={SYSTEMS[selected]} y700.generation={selected}")
        if missing:
            options = options.replace(f" y700.generation={selected}", "")
        path.write_text(f"title Board EFI lab {number}\nversion {number}\n"
                        f"linux /EFI/Linux/linux.efi\ninitrd /EFI/Linux/initrd-{number}.cpio\n"
                        "devicetree /EFI/Linux/qemu.dtb\n"
                        f"options {options}\n")
        run([mtools / "mcopy", "-o", "-i", disk, path,
             f"::/loader/entries/nixos-generation-{number}.conf"], env=env)

    entry(esp, 1)
    entry(esp, 2)

    def boot(label, disk, expected, reboot=False):
        variables = output / f"vars-{label}.fd"
        shutil.copyfile(var_template, variables)
        log = output / f"serial-{label}.log"
        cmd = [tools / "qemu/bin/qemu-system-aarch64", "-machine", "virt,gic-version=3",
               "-cpu", "cortex-a72", "-accel", "tcg", "-m", "1024", "-smp", "2",
               "-display", "none", "-monitor", "none", "-serial", f"file:{log}", "-nic", "none",
               "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={firmware}",
               "-drive", f"if=pflash,format=raw,unit=1,file={variables}",
               "-drive", f"if=none,id=esp,format=raw,readonly=on,file={disk}",
               "-device", "virtio-blk-pci,drive=esp,logical_block_size=4096,physical_block_size=4096",
               "-device", "virtio-scsi-device,id=scsi"]
        if not reboot:
            cmd += ["-no-reboot"]
        for i, path in enumerate([root, *other]):
            cmd += ["-drive", f"if=none,id=d{i},format=raw,file={path}",
                    "-device", f"scsi-hd,drive=d{i},bus=scsi.0,scsi-id=0,lun={i},"
                               "logical_block_size=4096,physical_block_size=4096"]
        dtb = output / "qemu.dtb"
        if not dtb.exists():
            # AAVMF defaults to ACPI and does not supply the QEMU platform DT.
            # Test the BLS DTB path too, using the exact emulated hardware tree.
            dump = cmd.copy()
            dump[2] += f",dumpdtb={dtb}"
            run(dump, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            run([mtools / "mcopy", "-i", disk, dtb, "::/EFI/Linux/qemu.dtb"], env=env)
            evidence["platform_dtb_sha256"] = sha(dtb)
        before = sha(disk)
        print(f"Starting board EFI lab {label}", flush=True)
        start = time.monotonic()
        with (output / f"qemu-{label}.log").open("xb") as errors:
            result = subprocess.run([str(x) for x in cmd], stdin=subprocess.DEVNULL,
                                    stdout=errors, stderr=errors, timeout=args.timeout)
        text = log.read_text(errors="replace")
        passed = result.returncode == 0 and all(x in text for x in expected) and "BOARD_EFI_FAIL=" not in text
        if reboot:
            passed &= text.count("BOARD_EFI_SELECTED=2") == 2 and text.count("BOARD_EFI_SELECTED=1") == 1
        record = dict(test=label, passed=bool(passed), seconds=round(time.monotonic() - start, 3),
                      qemu_exit=result.returncode, esp_unchanged=sha(disk) == before)
        evidence["runs"].append(record)
        report.write_text(json.dumps(evidence, indent=2) + "\n")
        if not passed or not record["esp_unchanged"]:
            raise RuntimeError(f"{label} failed: inspect {log}")
        print(f"{label}: passed", flush=True)

    boot("oneshot-cycle", esp, ["BOARD_EFI_ONESHOT_REQUESTED",
                               "BOARD_EFI_OLD_GENERATION_WITH_NEW_DEFAULT",
                               "BOARD_EFI_DEFAULT_RESTORED"], reboot=True)
    stable_root = sha(root)
    for label, selected, missing, message in (
        ("mismatch-refused", 1, False, "EFI entry does not match its initrd"),
        ("missing-selection-refused", 2, True, "EFI entry must select exactly one system"),
        ("absent-system-refused", 3, False, "rootfs lacks executable NixOS init"),
    ):
        disk = output / f"esp-{label}.img"
        run(["cp", "--reflink=auto", "--sparse=always", esp, disk])
        if selected == 3:
            # A well-formed entry/initrd for a store system absent from rootfs.
            run([mtools / "mcopy", "-o", "-i", disk, initrds[3],
                 "::/EFI/Linux/initrd-2.cpio"], env=env)
        entry(disk, 2, selected=selected, missing=missing)
        boot(label, disk, ["Rootfs handoff failed: " + message])
        if sha(root) != stable_root:
            raise RuntimeError(f"{label} wrote the root disk before refusing")
    if protected != {p.name: sha(p) for p in other} or boundaries != root_protected():
        raise RuntimeError("Protected Android disk bytes changed")
    if inputs != {name: sha(Path(name)) for name in inputs}:
        raise RuntimeError("Inputs changed during test")
    if any(sha(path) != evidence["initrds"][n]["sha256"] for n, path in initrds.items()):
        raise RuntimeError("Initrd inputs changed during test")
    evidence["android_sentinels_unchanged"] = True
    evidence["refusals_before_disk_writes"] = True
    evidence["oneshot_sequence"] = [2, 1, 2]
    report.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Board EFI handoff passed offline: {report}")


if __name__ == "__main__":
    main()
