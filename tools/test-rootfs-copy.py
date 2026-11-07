#!/usr/bin/env python3
"""Exercise journal diagnosis on synthetic regular files, without a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess


BLOCK = 4096
SIZE = 64 << 20


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def superblock(path):
    with path.open("rb") as stream:
        stream.seek(1024)
        data = stream.read(1024)
    require(len(data) == 1024, "short synthetic superblock")
    require(struct.unpack_from("<H", data, 0x38)[0] == 0xEF53, "ext4 magic")
    return {
        "state": struct.unpack_from("<H", data, 0x3A)[0],
        "needs_recovery": bool(struct.unpack_from("<I", data, 0x60)[0] & 4),
        "orphan_present": bool(struct.unpack_from("<I", data, 0x64)[0] & 0x10000),
    }


class Case:
    def __init__(self, path, tools):
        self.path = path
        self.path.mkdir()
        self.tools = tools
        self.commands = []

    def run(self, tool, *args, expected=(0,)):
        command = [str(self.tools[tool]), *map(str, args)]
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=30, env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )
        name = f"{len(self.commands):02d}-{tool}"
        (self.path / f"{name}.stdout").write_text(result.stdout)
        (self.path / f"{name}.stderr").write_text(result.stderr)
        self.commands.append({"argv": command, "exit": result.returncode, "log": name})
        require(result.returncode in expected,
                f"{tool} returned {result.returncode}; see {self.path / name}")
        return result.stdout + result.stderr

    def block(self, image, name):
        result = self.run("debugfs", "-R", f"blocks {name}", image)
        first = result.splitlines()[0].split()
        require(len(first) == 1 and first[0].isdigit(), "expected one data block")
        return int(first[0])

    def read_block(self, image, block):
        with image.open("rb") as stream:
            stream.seek(block * BLOCK)
            data = stream.read(BLOCK)
        require(len(data) == BLOCK, "short fixture block")
        return data

    def corrupt_checksum(self, image, block):
        # Change only the directory checksum, leaving its entries parseable.
        data = self.read_block(image, block)
        with image.open("r+b") as stream:
            stream.seek((block + 1) * BLOCK - 1)
            stream.write(bytes([data[-1] ^ 1]))

    def exercise(self, committed, residual):
        seed = self.path / "seed"
        (seed / "pending").mkdir(parents=True)
        (seed / "separate").mkdir()
        payload = b"LAB-ONLY-NOT-TABLET-DATA\n" * 100
        (seed / "pending/payload").write_bytes(payload)
        source = self.path / "source.ext4"
        with source.open("xb") as stream:
            stream.truncate(SIZE)
        self.run("mke2fs", "-q", "-t", "ext4", "-b", str(BLOCK), "-I", "256",
                 "-O", "metadata_csum,64bit,orphan_file",
                 "-E", "lazy_itable_init=0,lazy_journal_init=0",
                 "-d", seed, source)
        self.run("e2fsck", "-fn", source)
        pending_block = self.block(source, "/pending")
        separate_block = self.block(source, "/separate")
        payload_block = self.block(source, "/pending/payload")
        pending_bytes = self.read_block(source, pending_block)
        (self.path / "journal-data.bin").write_bytes(pending_bytes)
        journal_script = self.path / "journal.commands"
        prior_transaction = ""
        if not committed:
            (self.path / "prior-data.bin").write_bytes(
                self.read_block(source, separate_block))
            # Leave a committed transaction pending as well, so debugfs
            # retains a real recovery start before the uncommitted tail.
            prior_transaction = (
                f"journal_write -b {separate_block} {self.path}/prior-data.bin\n"
            )
        # debugfs -c suppresses the transaction's commit record here.
        uncommitted = "" if committed else "-c "
        journal_script.write_text(
            "journal_open -c -v 3\n"
            + prior_transaction +
            f"journal_write {uncommitted}-b {pending_block} "
            f"{self.path}/journal-data.bin\njournal_close\n"
        )
        self.run("debugfs", "-w", "-f", journal_script, source)
        self.corrupt_checksum(source, pending_block)
        if residual:
            self.corrupt_checksum(source, separate_block)
        source.chmod(0o444)
        source_hash = sha256(source)
        before = superblock(source)
        require(before["state"] == 1 and before["needs_recovery"],
                "fixture must have a clean-state bit and a real pending journal")
        precheck = self.run("e2fsck", "-fn", source, expected=(4,))
        require("skipping journal recovery" in precheck and
                "fails checksum" in precheck, "missing dirty-source evidence")

        # The metadata copy is diagnostic evidence, never a bootable rootfs.
        qcow = self.path / "metadata.qcow2"
        self.run("e2image", "-Q", source, qcow)
        qcow.chmod(0o444)
        qcow_hash = sha256(qcow)
        raw = self.path / "metadata.raw"
        self.run("e2image", "-r", qcow, raw)
        raw.chmod(0o444)
        raw_hash = sha256(raw)
        require(raw.stat().st_size == SIZE, "metadata image logical size")
        require(self.read_block(raw, payload_block) == bytes(BLOCK),
                "metadata fixture unexpectedly contains regular-file payload")
        require(self.read_block(source, payload_block).startswith(payload),
                "source lost its regular-file payload")
        self.run("e2fsck", "-fn", raw, expected=(4,))

        for image, name in ((source, "source"), (raw, "metadata")):
            self.run("debugfs", "-R", f"dump <8> {self.path}/{name}.journal", image)
        source_journal = (self.path / "source.journal").read_bytes()
        metadata_journal = (self.path / "metadata.journal").read_bytes()
        require(source_journal == metadata_journal, "journal not preserved")
        require(struct.unpack_from(">I", source_journal, 28)[0] != 0,
                "synthetic journal must not be empty")
        self.run("debugfs", "-R", "logdump -n 8", raw)
        records = [
            struct.unpack_from(">III", source_journal, offset)
            for offset in range(BLOCK, len(source_journal), BLOCK)
            if struct.unpack_from(">I", source_journal, offset)[0] == 0xC03B3998
        ]
        descriptors = [seq for _, kind, seq in records if kind == 1]
        commits = [seq for _, kind, seq in records if kind == 2]
        require(len(descriptors) == (1 if committed else 2) and len(commits) == 1,
                "unexpected descriptor/commit count")
        require((descriptors[-1] in commits) == committed,
                "unexpected directory-repair commit state")

        working = self.path / "working.raw"
        shutil.copyfile(raw, working)
        self.run("e2fsck", "-E", "journal_only", "-p", working)
        after = superblock(working)
        require(not after["needs_recovery"], "working-copy journal not processed")
        should_pass = committed and not residual
        self.run("e2fsck", "-fn", working, expected=(0 if should_pass else 4,))
        if committed:
            require(self.read_block(working, pending_block) == pending_bytes,
                    "committed directory block was not replayed")
        else:
            require(self.read_block(working, pending_block) != pending_bytes,
                    "uncommitted transaction was unexpectedly replayed")
        require(sha256(source) == source_hash, "source image changed")
        require(sha256(qcow) == qcow_hash, "captured metadata changed")
        require(sha256(raw) == raw_hash, "untouched raw metadata changed")
        result = {
            "directory_repair_transaction_committed": committed,
            "journal_descriptors": descriptors,
            "journal_commits": commits,
            "independent_directory_corruption": residual,
            "before": before, "working_copy_after_journal_only": after,
            "full_check_after_replay": 0 if should_pass else 4,
            "journal_preserved": True,
            "regular_file_data_omitted": True,
            "source_unchanged": True,
            "capture_unchanged": True,
            "source_sha256": source_hash,
            "metadata_qcow2_sha256": qcow_hash,
            "metadata_raw_sha256": raw_hash,
            "working_raw_sha256": sha256(working),
            "commands": self.commands,
        }
        (self.path / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        return {k: v for k, v in result.items() if k != "commands"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True,
                        help="new directory for generated fixtures; no source/device argument")
    args = parser.parse_args()
    output = args.out.absolute()
    # debugfs command files do not use shell quoting; keep fixture paths simple.
    require(all(c.isascii() and (c.isalnum() or c in "/._-") for c in str(output)),
            "output path must contain only ASCII letters, digits, slash, dot, dash, underscore")
    require(not output.exists() and not output.is_symlink(), "output must be new")
    tools = {}
    for name in ("mke2fs", "e2image", "e2fsck", "debugfs"):
        binary = shutil.which(name)
        require(binary is not None, f"missing tool: {name}")
        tools[name] = Path(binary).resolve(strict=True)
    output.mkdir(parents=True)
    output = output.resolve(strict=True)
    cases = {}
    for name, committed, residual in (
        ("committed-recovery", True, False),
        ("residual-corruption", True, True),
        ("uncommitted-transaction", False, False),
    ):
        cases[name] = Case(output / name, tools).exercise(committed, residual)
    report = {
        "scope": "synthetic host regular files only; no tablet, mount or boot",
        "limits": [
            "Not a copy of the tablet and not a filesystem-consistency clearance.",
            "Metadata capture omits file payload and cannot serve as a rootfs backup.",
            "Does not cover crash-era allocations, orphan processing or all damaged layouts.",
            "Journal replay on a working copy cannot make the physical source consistent.",
        ],
        "tools": {n: {"path": str(p), "sha256": sha256(p)} for n, p in tools.items()},
        "cases": cases,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: three synthetic journal-copy cases; report: {output / 'report.json'}")


if __name__ == "__main__":
    main()
