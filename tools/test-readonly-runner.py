#!/usr/bin/env python3
"""Exercise the actual native static supervisor, including failure lifecycles."""
import argparse
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runner", "child", "reader", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    out = args.out.absolute()
    out.mkdir(mode=0o700)
    runner, child, reader = (str(p.resolve(strict=True)) for p in
                             (args.runner, args.child, args.reader))
    cases = []
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0

    def command(mode, *extra, wall=500, cpu=2, program=child):
        return [runner, str(wall), "100", "1000", "512", str(cpu), "--",
                program, mode, *extra]

    def record(name, result, expected, duration, clean=True):
        (out / f"{name}.stdout").write_bytes(result.stdout)
        (out / f"{name}.stderr").write_bytes(result.stderr)
        assert result.returncode == expected, (name, result.returncode, result.stderr[-1000:])
        assert duration < 6, (name, duration)
        if clean:
            assert re.search(rb"event=done result=" + str(expected).encode() +
                             rb" clean=1 .*?\n$", result.stderr), (name, result.stderr[-1000:])
        if child_pid := re.search(rb"event=child pid=(\d+)", result.stderr):
            try:
                os.kill(int(child_pid[1]), 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError((name, "child still exists"))
        cases.append({"case": name, "exit": expected, "seconds": round(duration, 4),
                      "terminal_clean_required": clean})

    def run(name, argv, expected=0, clean=True):
        started = time.monotonic()
        result = subprocess.run(argv, capture_output=True, timeout=6)
        record(name, result, expected, time.monotonic() - started, clean)
        return result

    def wait_stage(proc, marker):
        deadline = time.monotonic() + 3
        prefix = b""
        while marker not in prefix:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([proc.stderr], [], [], left)[0]:
                proc.kill()
                proc.communicate(timeout=2)
                raise AssertionError("missing bounded startup marker")
            chunk = os.read(proc.stderr.fileno(), 4096)
            if not chunk:
                proc.wait(timeout=2)
                raise AssertionError(("early startup exit", proc.returncode, prefix))
            prefix += chunk
        return prefix

    run("limits", command("probe"))
    run("self-probe", command("--probe", program=runner))
    run("exit-seven", command("exit", "7"), 7)
    run("abort", command("abort"), 128 + signal.SIGABRT)
    run("cpu-limit", command("cpu", wall=4000, cpu=1), 128 + signal.SIGXCPU)
    run("ignore-term", command("hang"), 124)
    run("escaped-descendant", command("descendant"), 125)
    run("parent-reservations", [child, "reserve-parent", *command("probe")])
    run("reject-dynamic", command("", program=str(Path("/proc/self/exe").resolve())), 125, False)
    run("reject-missing", command("", program=str(out / "missing")), 125, False)
    noexec = out / "noexec"
    noexec.write_bytes(Path(child).read_bytes())
    noexec.chmod(0o600)
    run("exec-permission", command("probe", program=str(noexec)), 127)

    started = time.monotonic()
    proc = subprocess.Popen(command("floodout"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.wait(timeout=4)
    stdout, stderr = proc.communicate(timeout=1)
    record("blocked-stdout", subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr),
           124, time.monotonic() - started)

    started = time.monotonic()
    proc = subprocess.Popen(command("floodout"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdout.close()
    proc.wait(timeout=4)
    stderr = proc.stderr.read()
    record("closed-stdout", subprocess.CompletedProcess(proc.args, proc.returncode, b"", stderr),
           128 + signal.SIGPIPE, time.monotonic() - started)

    started = time.monotonic()
    proc = subprocess.Popen(command("flooderr"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.wait(timeout=4)
    stdout, stderr = proc.communicate(timeout=1)
    record("blocked-stderr", subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr),
           125, time.monotonic() - started, False)

    started = time.monotonic()
    proc = subprocess.Popen(command("hang", wall=4000), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    prefix = wait_stage(proc, b"event=limits_ready\n")
    proc.terminate()
    stdout, stderr = proc.communicate(timeout=4)
    record("supervisor-term", subprocess.CompletedProcess(proc.args, proc.returncode, stdout, prefix + stderr),
           128 + signal.SIGTERM, time.monotonic() - started)

    started = time.monotonic()
    proc = subprocess.Popen(command("hang", wall=4000), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    prefix = wait_stage(proc, b"event=exec_pipe_closed\n")
    proc.stderr.close()
    proc.wait(timeout=2)
    stdout = proc.stdout.read()
    record("closed-stderr-quiet-child",
           subprocess.CompletedProcess(proc.args, proc.returncode, stdout, prefix),
           125, time.monotonic() - started, False)
    assert time.monotonic() - started < 2

    proc = subprocess.Popen(command("hang", wall=4000), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    prefix = wait_stage(proc, b"event=limits_ready\n")
    target = int(re.search(rb"event=child pid=(\d+)", prefix)[1])
    proc.kill()
    proc.wait(timeout=2)
    deadline = time.monotonic() + 2
    while True:
        found, status = os.waitpid(target, os.WNOHANG)
        if found:
            assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
            break
        assert time.monotonic() < deadline, "parent-death child remains"
        time.sleep(0.01)
    stdout, stderr = proc.communicate(timeout=1)
    assert b"event=done" not in prefix + stderr
    (out / "parent-death.stderr").write_bytes(prefix + stderr)
    cases.append({"case": "parent-death", "child_signal": "SIGKILL",
                  "no_false_terminal_marker": True})

    source = out / "source"
    source.write_bytes(bytes(range(256)) * 256)
    source_before = hashlib.sha256(source.read_bytes()).hexdigest()
    plan = out / "ranges"
    plan.write_text("0 1\n3 2\n")
    result = run("range-reader", command("--file", str(source), "65536", str(plan), program=reader))
    assert result.stdout == source.read_bytes()[:4096] + source.read_bytes()[12288:20480]
    for i, bad in enumerate(("1 1\n", "0 1\n0 1\n", "0 0\n", "0 257\n",
                             "0 17\n", "-1 1\n", "0 1", "0 1 extra\n")):
        plan.write_text(bad)
        run(f"reject-range-{i}", command("--file", str(source), "65536", str(plan), program=reader), 4)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_before
    probe = run("base64-probe", command("--probe-base64", program=reader))
    assert probe.stdout == base64.b64encode(bytes(range(256)) * 256)
    encoded_source = out / "encoding-source"
    encoded_data = bytes(range(256)) * 512
    encoded_source.write_bytes(encoded_data)
    for i, ranges in enumerate(([(0, 1)], [(0, 2)], [(0, 3)], [(0, 17)],
                                [(0, 1), (3, 2)])):
        plan.write_text("".join(f"{first} {count}\n" for first, count in ranges))
        result = run(f"base64-ranges-{i}", command(
            "--base64", "--file", str(encoded_source), str(len(encoded_data)),
            str(plan), program=reader))
        expected = b"".join(encoded_data[first * 4096:(first + count) * 4096]
                            for first, count in ranges)
        assert result.stdout == base64.b64encode(expected)
        assert (f"Y700_RANGE_READER_V2 event=done bytes={len(expected)} "
                f"encoding=base64 encoded_bytes={len(result.stdout)}\n").encode() in result.stderr
    assert encoded_source.read_bytes() == encoded_data
    report = {"cases": cases, "count": len(cases), "source_unchanged": True,
              "no_device_operations": True,
              "tools": {name: {"path": path, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
                        for name, path in (("runner", runner), ("child", child), ("reader", reader))}}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": len(cases), "report": str(out / "report.json")}))


if __name__ == "__main__":
    main()
