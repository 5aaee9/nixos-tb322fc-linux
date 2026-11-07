#!/usr/bin/env python3
"""Test the actual RAM provider in QEMU, with no external EFI firmware or disk."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--entries", choices=("a", "b", "both"), default="both")
    args = parser.parse_args()
    provider = args.provider.resolve(strict=True)
    policy = json.loads((provider / "provider-policy.json").read_text())
    media = json.loads((provider / "media.json").read_text())
    if policy["scope"] != "QEMU lab only" or media["default"] != "a":
        parser.error("requires a QEMU-only provider with lab-a as its default")
    image = provider / "u-boot.bin"
    qemu = args.qemu.resolve(strict=True)
    args.out.mkdir(parents=True, exist_ok=False)
    evidence = {
        "scope": "actual RAM provider in QEMU; no TB322FC acceptance",
        "provider": str(image), "sha256": sha256(image),
        "qemu": str(qemu), "qemu_sha256": sha256(qemu),
        "media": media, "runs": [],
    }
    entries = ("a", "b") if args.entries == "both" else (args.entries,)
    for entry in entries:
        command = [
            str(qemu), "-machine", "virt,gic-version=3", "-cpu", "cortex-a72",
            "-accel", "tcg", "-m", "2048", "-smp", "2",
            "-display", "none", "-monitor", "none", "-serial", "stdio",
            "-nic", "none", "-no-reboot", "-kernel", str(image),
        ]
        started = time.monotonic()
        record = {"entry": entry, "argv": command, "selection_sent": False}
        log = bytearray()
        timed_out = False
        with (args.out / f"serial-{entry}.log").open("xb") as stream:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, bufsize=0)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while selector.get_map():
                        if time.monotonic() - started > args.timeout:
                            timed_out = True
                            process.kill()
                        for key, _ in selector.select(timeout=0.2):
                            chunk = os.read(key.fileobj.fileno(), 65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            stream.write(chunk)
                            stream.flush()
                            log.extend(chunk)
                            # The B entry sorts first. Select it in the real
                            # systemd-boot menu; the provider remains identical.
                            if (entry == "b" and not record["selection_sent"]
                                    and b"Boot in " in log
                                    and b"RAM UEFI test B" in log):
                                process.stdin.write(b"\x1b[H\r")
                                process.stdin.flush()
                                record["selection_sent"] = True
                                record["selection_keys_hex"] = "1b5b480d"
                returncode = process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdin.close()
                process.stdout.close()
        text = log.decode(errors="replace")
        record.update(
            seconds=round(time.monotonic() - started, 3), exit=returncode,
            timed_out=timed_out,
            passed=(returncode == 0 and not timed_out
                    and "Y700_RAM_UEFI_PROVIDER=v1 mode=qemu-lab" in text
                    and "Y700_EFI_LAB_LOADER=systemd-boot" in text
                    and f"Y700_EFI_LAB_ENTRY=lab-{entry}.conf" in text
                    and f"Y700_EFI_LAB_PASS={entry}" in text
                    and (entry == "a" or record["selection_sent"])),
        )
        evidence["runs"].append(record)
        evidence["unchanged_provider"] = sha256(image) == evidence["sha256"]
        (args.out / "metadata.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(f"RAM provider entry {entry}: {record}", flush=True)
        if not record["passed"] or not evidence["unchanged_provider"]:
            raise SystemExit(f"Provider test failed; inspect {args.out}")


if __name__ == "__main__":
    main()
