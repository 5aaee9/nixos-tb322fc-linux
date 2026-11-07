#!/usr/bin/env python3
"""Validate static ARM64 capture tools in a diskless system-QEMU guest."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import time


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runner", "child", "reader", "e2image", "busybox", "gen-init-cpio",
                 "tools", "fixtures", "expected-maps", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--baseline-runner", type=Path,
                        help="Unmodified old ARM64 supervisor for the no-proc control")
    args = parser.parse_args()
    output = args.out.absolute()
    output.mkdir(mode=0o700)
    paths = {name: value.resolve(strict=True) for name, value in vars(args).items()
             if name != "out" and value is not None}
    assert all(" " not in str(path) and "\n" not in str(path)
               for path in (*paths.values(), output))
    qemu = paths["tools"] / "qemu/bin/qemu-system-aarch64"
    kernel = paths["tools"] / "kernel/Image"
    listing = [
        "dir /bin 0755 0 0", "dir /dev 0755 0 0", "dir /proc 0755 0 0",
        "dir /run 0700 0 0", "dir /fixtures 0700 0 0",
        "nod /dev/console 0600 0 0 c 5 1", "nod /dev/null 0666 0 0 c 1 3",
        "slink /bin/sh busybox 0755 0 0",
    ]
    for name in ("runner", "child", "reader", "e2image", "busybox"):
        target = "/bin/busybox" if name == "busybox" else "/" + name
        listing.append(f"file {target} {paths[name]} 0555 0 0")
    if args.baseline_runner:
        listing.append(f"file /baseline-runner {paths['baseline_runner']} 0555 0 0")
    fixture_records = []
    script = """#!/bin/sh
BB=/bin/busybox
fail() { echo "RUNNER_ARM_FAIL=$*"; $BB poweroff -f; while :; do $BB sleep 1; done; }
trap 'fail shell-error' EXIT
set -eu
check_state() {
    name=$1; expected=$2; clean=$3; shift 3
    rc=0
    "$@" > "/run/$name.out" 2> "/run/$name.err" || rc=$?
    $BB cat "/run/$name.err"
    [ "$rc" = "$expected" ] || fail "$name-exit-$rc"
    $BB grep -Eq "event=done result=$expected clean=$clean " "/run/$name.err" ||
        fail "$name-clean"
    echo "RUNNER_ARM_CASE=$name:$rc"
}
check() {
    name=$1; expected=$2; shift 2
    check_state "$name" "$expected" 1 "$@"
}
[ ! -e /proc/self ] || fail unexpected-proc-before-tests
"""
    if args.baseline_runner:
        script += """
check_state no-proc-control 125 0 /baseline-runner 2000 100 1000 512 2 -- /baseline-runner --probe
$BB grep -qx 'Y700_RUNNER_PROBE_V1 as_bytes=536870912 core_bytes=0 limit_enforced=1' /run/no-proc-control.out ||
    fail no-proc-control-probe
"""
    script += """
check no-proc-self-probe 0 /runner 2000 100 1000 512 2 -- /runner --probe
$BB grep -qx 'Y700_RUNNER_PROBE_V1 as_bytes=536870912 core_bytes=0 limit_enforced=1' /run/no-proc-self-probe.out ||
    fail no-proc-corrected-probe
if $BB grep -q 'event=cleanup_error' /run/no-proc-self-probe.err; then
    fail no-proc-unnecessary-inspection
fi
check no-proc-exit-seven 7 /runner 2000 100 1000 512 2 -- /child exit 7
check no-proc-abort 134 /runner 2000 100 1000 512 2 -- /child abort
check no-proc-ignore-term 124 /runner 500 100 1000 512 2 -- /child hang
check_state no-proc-escaped-descendant 125 0 /runner 2000 100 1000 512 2 -- /child descendant
$BB grep -qx 'Y700_RUNNER_V1 event=cleanup_error operation=children_open errno=2 fatal=0' /run/no-proc-escaped-descendant.err ||
    fail no-proc-missing-inspection-error
$BB grep -qx 'Y700_RUNNER_V1 event=reap_deadline leader_reaped=1' /run/no-proc-escaped-descendant.err ||
    fail no-proc-missing-deadline
[ ! -e /proc/self ] || fail unexpected-proc-after-tests
$BB mount -t proc proc /proc
case "$($BB cat /proc/sys/kernel/core_pattern)" in \\|*) fail core-pipe;; esac
orphan=$($BB sed -n 's/^DESCENDANT pid=\\([0-9][0-9]*\\)$/\\1/p' /run/no-proc-escaped-descendant.out)
[ -n "$orphan" ] || fail no-proc-missing-orphan
$BB awk '$3=="S" { good=1 } END { exit !good }' "/proc/$orphan/stat" ||
    fail no-proc-orphan-not-alive
echo RUNNER_ARM_UNACCOUNTED_CHILD=alive-until-guest-shutdown
check limits 0 /runner 2000 100 1000 512 2 -- /child probe
$BB cat /run/limits.out
check self-probe 0 /runner 2000 100 1000 512 2 -- /runner --probe
$BB cat /run/self-probe.out
check exit-seven 7 /runner 2000 100 1000 512 2 -- /child exit 7
check abort 134 /runner 2000 100 1000 512 2 -- /child abort
check cpu-limit 152 /runner 4000 100 1000 512 1 -- /child cpu
check ignore-term 124 /runner 500 100 1000 512 2 -- /child hang
check escaped-descendant 125 /runner 2000 100 1000 512 2 -- /child descendant
check parent-reservations 0 /child reserve-parent /runner 2000 100 1000 512 2 -- /child probe
$BB cat /run/parent-reservations.out
check base64-probe 0 /runner 2000 100 1000 512 2 -- /reader --probe-base64
hash_is() {
    actual=$($BB sha256sum "$1")
    [ "${actual%% *}" = "$2" ] || fail "hash-$1"
}
"""
    probe_wire = base64.b64encode(bytes(range(256)) * 256)
    script += f"hash_is /run/base64-probe.out {hashlib.sha256(probe_wire).hexdigest()}\n"
    for name in ("committed-recovery", "residual-corruption", "uncommitted-transaction"):
        source = paths["fixtures"] / name / "source.ext4"
        expected = paths["fixtures"] / name / "metadata.raw"
        old_map = paths["expected_maps"] / (name + ".map")
        assert source.is_file() and source.stat().st_size == 64 << 20
        source_hash, raw_hash, map_hash = (digest(p) for p in (source, expected, old_map))
        listing.append(f"file /fixtures/{name} {source} 0400 0 0")
        # Reconstruction is solely in the guest RAM filesystem.
        script += f"""
hash_is /fixtures/{name} {source_hash}
check {name}-map 0 /runner 120000 100 1000 512 60 -- /e2image -r -n /fixtures/{name} -
hash_is /run/{name}-map.out {map_hash}
$BB awk '
BEGIN {{ last=-1; start=0; count=0 }}
{{ if ($1!="Writing" || $2!="block" || NF!=3 || $3<=last || $3>=16384) exit 2;
   block=$3; if (NR==1 && block!=0) exit 2;
   if (count && (block!=last+1 || count==256)) {{ print start, count; count=0 }}
   if (!count) start=block; count++; last=block }}
END {{ if (!count) exit 3; print start, count }}
' /run/{name}-map.out > /run/{name}.ranges
check {name}-reader 0 /runner 120000 100 1000 512 60 -- /reader --file /fixtures/{name} 67108864 /run/{name}.ranges
check {name}-base64 0 /runner 120000 100 1000 512 60 -- /reader --base64 --file /fixtures/{name} 67108864 /run/{name}.ranges
$BB base64 -d /run/{name}-base64.out > /run/{name}.decoded
$BB cmp /run/{name}-reader.out /run/{name}.decoded || fail {name}-base64-bytes
$BB dd if=/dev/null of=/run/{name}.raw bs=4096 seek=16384 2>/dev/null
skip=0
while read start count; do
    $BB dd if=/run/{name}-reader.out of=/run/{name}.raw bs=4096 skip=$skip seek=$start count=$count conv=notrunc 2>/dev/null
    skip=$((skip + count))
done < /run/{name}.ranges
hash_is /run/{name}.raw {raw_hash}
hash_is /fixtures/{name} {source_hash}
echo 'RUNNER_ARM_METADATA={name}:exact:source-unchanged'
"""
        fixture_records.append({"fixture": name, "source": str(source),
                                "source_sha256": source_hash, "map_sha256": map_hash,
                                "metadata_sha256": raw_hash})
    script += """
$BB dd if=/dev/null of=/run/bad-magic bs=4096 seek=16384 2>/dev/null
before=$($BB sha256sum /run/bad-magic)
check bad-magic 1 /runner 2000 100 1000 512 2 -- /e2image -r -n /run/bad-magic -
[ "$before" = "$($BB sha256sum /run/bad-magic)" ] || fail bad-magic-changed
[ "$($BB cat /run/bad-magic.out)" = "Couldn't find valid filesystem superblock." ] ||
    fail bad-magic-diagnostic
echo RUNNER_ARM_PASS
trap - EXIT
$BB poweroff -f
while :; do $BB sleep 1; done
"""
    init = output / "init"
    init.write_text(script)
    listing.append(f"file /init {init} 0755 0 0")
    manifest = output / "initramfs.list"
    manifest.write_text("\n".join(listing) + "\n")
    cpio = output / "initramfs.cpio.gz"
    with cpio.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as stream:
            proc = subprocess.Popen([str(paths["gen_init_cpio"]), "-t", "0", str(manifest)],
                                    stdout=subprocess.PIPE)
            while chunk := proc.stdout.read(1 << 20):
                stream.write(chunk)
            assert proc.wait(timeout=10) == 0
    command = [str(qemu), "-machine", "virt,gic-version=3", "-cpu", "cortex-a72",
               "-m", "2048", "-smp", "2", "-nodefaults", "-nographic",
               "-serial", "stdio", "-monitor", "none", "-nic", "none", "-no-reboot",
               "-kernel", str(kernel), "-initrd", str(cpio),
               "-append", "console=ttyAMA0 rdinit=/init panic=-1"]
    started = time.monotonic()
    with (output / "console.log").open("xb") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    console = (output / "console.log").read_text(errors="replace")
    assert "RUNNER_ARM_FAIL=" not in console, console[-3000:]
    assert "RUNNER_ARM_PASS" in console, console[-3000:]
    case_count = 24 + bool(args.baseline_runner)
    assert console.count("RUNNER_ARM_CASE=") == case_count
    assert console.count("RUNNER_ARM_METADATA=") == 3
    assert "RUNNER_ARM_UNACCOUNTED_CHILD=alive-until-guest-shutdown" in console
    assert "PARENT reservation_bytes=12884901888 limits_unchanged=1" in console
    for item in fixture_records:
        assert digest(Path(item["source"])) == item["source_sha256"]
    tools = {name: {"path": str(paths[name]), "sha256": digest(paths[name])}
             for name in ("runner", "child", "reader", "e2image", "busybox", "gen_init_cpio")}
    tools.update({name: {"path": str(path), "sha256": digest(path)}
                  for name, path in (("qemu", qemu), ("kernel", kernel))})
    if args.baseline_runner:
        tools["baseline_runner"] = {"path": str(paths["baseline_runner"]),
                                    "sha256": digest(paths["baseline_runner"])}
    report = {"no_device_operations": True, "no_guest_disk_or_network": True,
              "guest_proc_only_mount": True, "case_count": case_count,
              "no_proc_cases": 5, "baseline_control": bool(args.baseline_runner),
              "unaccounted_child_rejected": True,
              "seconds": round(time.monotonic() - started, 3),
              "metadata_cases": fixture_records, "tools": tools,
              "initramfs_sha256": digest(cpio), "script_sha256": digest(Path(__file__)),
              "console_sha256": digest(output / "console.log")}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(output / "report.json")


if __name__ == "__main__":
    main()
