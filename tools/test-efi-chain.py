#!/usr/bin/env python3
"""Test ARM64 systemd-boot/EFI-stub interoperability in QEMU, never on a tablet."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

PROJECT = Path(__file__).resolve().parents[1]
LOADER_GUID = "4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, **kwargs)


def initramfs(output, generation, busybox, gen_cpio):
    script = output / f"init-{generation}"
    script.write_text(f"""#!/bin/sh
BB=/bin/busybox
$BB mount -t proc proc /proc
$BB mount -t sysfs sysfs /sys
$BB mount -t devtmpfs devtmpfs /dev
exec >/dev/console 2>&1
fail() {{
    echo "Y700_EFI_LAB_FAIL=$*"
    $BB poweroff -f
    while :; do $BB sleep 1; done
}}
echo "Y700_EFI_LAB_INITRD={generation}"
test "$($BB uname -m)" = aarch64 || fail architecture
test "$($BB cat /sys/firmware/efi/fw_platform_size)" = 64 || fail efi-platform
case " $($BB cat /proc/cmdline) " in
    *" y700.lab-generation={generation} "*) ;;
    *) fail wrong-entry ;;
esac
$BB mount -t efivarfs efivarfs /sys/firmware/efi/efivars || fail efivars
loader=$($BB dd if=/sys/firmware/efi/efivars/LoaderInfo-{LOADER_GUID} bs=1 skip=4 2>/dev/null | $BB tr -d '\\000')
case "$loader" in systemd-boot*) ;; *) fail wrong-loader ;; esac
echo "Y700_EFI_LAB_LOADER=$loader"
entry=$($BB dd if=/sys/firmware/efi/efivars/LoaderEntrySelected-{LOADER_GUID} bs=1 skip=4 2>/dev/null | $BB tr -d '\\000')
test "$entry" = lab-{generation}.conf || fail wrong-selected-entry
echo "Y700_EFI_LAB_ENTRY=$entry"
echo "Y700_EFI_LAB_PASS={generation}"
$BB poweroff -f
while :; do $BB sleep 1; done
""")
    listing = output / f"initramfs-{generation}.list"
    listing.write_text("\n".join([
        "dir /bin 0755 0 0", "dir /dev 0755 0 0", "dir /proc 0755 0 0",
        "dir /sys 0755 0 0", "nod /dev/console 0600 0 0 c 5 1",
        f"file /bin/busybox {busybox} 0755 0 0",
        "slink /bin/sh busybox 0755 0 0",
        f"file /init {script} 0755 0 0", "",
    ]))
    result = output / f"initrd-{generation}.cpio"
    with result.open("xb") as stream:
        run([gen_cpio, "-t", "0", listing], stdout=stream)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, default=PROJECT / "result-efi-lab-tools")
    parser.add_argument("--busybox", type=Path, default=PROJECT / "result-busybox/bin/busybox")
    parser.add_argument("--gen-init-cpio", type=Path, default=PROJECT / "result-gen-init-cpio/bin/gen_init_cpio")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--kernel", type=Path, help="Optional board EFI Image; defaults to the generic lab kernel")
    args = parser.parse_args()
    output = args.out.absolute()
    if output.exists():
        parser.error("output must not already exist; evidence is immutable")
    tools = args.tools.resolve(strict=True)
    qemu = tools / "qemu/bin/qemu-system-aarch64"
    mtools = tools / "mtools/bin"
    loader = tools / "systemd/lib/systemd/boot/efi/systemd-bootaa64.efi"
    kernel = args.kernel.resolve(strict=True) if args.kernel else tools / "kernel/Image"
    firmware = next((tools / "firmware").rglob("AAVMF_CODE.fd"))
    var_template = next((tools / "firmware").rglob("AAVMF_VARS.fd"))
    busybox = args.busybox.resolve(strict=True)
    gen_cpio = args.gen_init_cpio.resolve(strict=True)
    for path in (qemu, loader, kernel, firmware, var_template, busybox, gen_cpio):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    if any(" " in str(path) for path in (busybox, output)):
        parser.error("gen_init_cpio inputs must not contain spaces")
    output.mkdir(parents=True)
    inputs = {str(path.resolve()): sha256(path)
              for path in (loader, kernel, firmware, var_template, busybox, gen_cpio)}
    evidence = {"scope": "QEMU ARM64 only; not TB322FC or NixOS generation acceptance",
                "nixpkgs": json.loads((PROJECT / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"],
                "inputs": inputs, "runs": []}
    (output / "metadata.json").write_text(json.dumps(evidence, indent=2) + "\n")
    initrds = {gen: initramfs(output, gen, busybox, gen_cpio) for gen in ("a", "b")}
    esp = output / "esp-base.img"
    with esp.open("xb") as stream:
        stream.truncate(256 * 1024 * 1024)
    env = os.environ | {"MTOOLSRC": "/dev/null"}
    run([mtools / "mformat", "-i", esp, "-F", "::"], env=env)
    run([mtools / "mmd", "-i", esp, "::/EFI", "::/EFI/BOOT", "::/EFI/Linux",
         "::/loader", "::/loader/entries"], env=env)
    run([mtools / "mcopy", "-i", esp, loader, "::/EFI/BOOT/BOOTAA64.EFI"], env=env)
    run([mtools / "mcopy", "-i", esp, kernel, "::/EFI/Linux/Image"], env=env)
    for gen in ("a", "b"):
        run([mtools / "mcopy", "-i", esp, initrds[gen],
             f"::/EFI/Linux/initrd-{gen}.cpio"], env=env)
        entry = output / f"lab-{gen}.conf"
        entry.write_text(f"""title ARM64 EFI lab {gen.upper()}
version {gen}
linux /EFI/Linux/Image
initrd /EFI/Linux/initrd-{gen}.cpio
options console=ttyAMA0 rdinit=/init panic=5 y700.lab-generation={gen}
""")
        run([mtools / "mcopy", "-i", esp, entry, f"::/loader/entries/lab-{gen}.conf"], env=env)
    for gen in ("a", "b"):
        disk = output / f"esp-{gen}.img"
        run(["cp", "--reflink=auto", "--sparse=always", esp, disk])
        loader_config = output / f"loader-{gen}.conf"
        loader_config.write_text(f"default lab-{gen}.conf\ntimeout 2\neditor no\nauto-firmware no\n")
        run([mtools / "mcopy", "-i", disk, loader_config, "::/loader/loader.conf"], env=env)
        variables = output / f"vars-{gen}.fd"
        shutil.copyfile(var_template, variables)
        log = output / f"serial-{gen}.log"
        command = [qemu, "-machine", "virt,gic-version=3", "-cpu", "cortex-a72",
                   "-accel", "tcg", "-m", "1024", "-smp", "2", "-display", "none",
                   "-monitor", "none", "-serial", f"file:{log}", "-nic", "none",
                   "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={firmware}",
                   "-drive", f"if=pflash,format=raw,unit=1,file={variables}",
                   "-drive", f"if=virtio,format=raw,readonly=on,file={disk}"]
        started = time.monotonic()
        print(f"Starting offline ARM64 EFI entry {gen}; timeout {args.timeout}s", flush=True)
        with (output / f"qemu-{gen}.log").open("xb") as diagnostic:
            result = subprocess.run([str(x) for x in command], stdin=subprocess.DEVNULL,
                                    stdout=diagnostic, stderr=subprocess.STDOUT,
                                    timeout=args.timeout)
        text = log.read_text(errors="replace")
        record = {"entry": gen, "seconds": round(time.monotonic() - started, 3),
                  "qemu_exit": result.returncode, "esp_sha256": sha256(disk),
                  "initrd_sha256": sha256(initrds[gen]),
                  "pass": result.returncode == 0 and f"Y700_EFI_LAB_PASS={gen}" in text}
        evidence["runs"].append(record)
        (output / "metadata.json").write_text(json.dumps(evidence, indent=2) + "\n")
        if not record["pass"]:
            raise SystemExit(f"EFI lab entry {gen} failed; inspect {log} and qemu-{gen}.log")
        print(f"Entry {gen} passed: systemd-boot -> ARM64 EFI Linux -> distinct RAM initrd", flush=True)
    if {path: sha256(path) for path in inputs} != inputs:
        raise SystemExit("EFI/kernel inputs changed during the test")
    evidence["unchanged_firmware_loader_kernel"] = True
    (output / "metadata.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Both entries passed; evidence: {output / 'metadata.json'}")


if __name__ == "__main__":
    main()
