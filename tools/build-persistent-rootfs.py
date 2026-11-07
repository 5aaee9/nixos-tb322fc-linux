#!/usr/bin/env python3
"""Build a registered NixOS install tarball locally; never open a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import time

PROJECT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--closure-info", type=Path)
    parser.add_argument("--profile", choices=("persistent", "desktop", "base"), default="persistent")
    args = parser.parse_args()
    system = args.system.resolve(strict=True)
    output = args.out.absolute()
    if output.exists():
        parser.error("output must not already exist")
    if system.parent != Path("/nix/store") or not (system / "init").is_file():
        parser.error("system must resolve to a built NixOS store path")
    try:
        bootspec = json.loads((system / "boot.json").read_text())["org.nixos.bootspec.v1"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        parser.error(f"system is missing a NixOS bootspec: {exc}")
    if (bootspec.get("system") != "aarch64-linux" or
            bootspec.get("toplevel") != str(system) or
            bootspec.get("init") != str(system / "init")):
        parser.error("system must be the matching aarch64-linux NixOS toplevel")
    if args.profile == "persistent" and not (system / "etc/systemd/system/y700-local-root-prepare-shutdown.service").exists():
        parser.error("system does not contain the persistent-root shutdown check")
    started = time.monotonic()
    output.mkdir(parents=True, mode=0o700)
    stage = output / "root"
    stage.mkdir()
    if args.closure_info:
        closure = sorted(set((args.closure_info / "store-paths").read_text().splitlines()))
        registration = (args.closure_info / "registration").read_bytes()
    else:
        closure = sorted(set(subprocess.check_output(
            ["nix-store", "--query", "--requisites", str(system)], text=True).splitlines()))
        registration = subprocess.check_output(["nix-store", "--dump-db", *closure])
    (output / "closure.txt").write_text("\n".join(closure) + "\n")
    (output / "registration.txt").write_bytes(registration)
    for directory in ("nix/store", "nix/var/nix/profiles", "nix/var/nix/gcroots",
                      "dev", "proc", "sys", "run", "tmp", "var", "home", "root",
                      "etc", "usr", "bin", "sbin", "lib", "lib64", "mnt", "boot"):
        (stage / directory).mkdir(parents=True, exist_ok=True)
    for path in closure:
        run("cp", "-a", "--reflink=auto", "--no-preserve=ownership",
            path, stage / "nix/store")
    # Nix's rooted local store separates BOTH database and store from the host.
    store = f"local?root={stage}"
    env = os.environ | {"NIX_REMOTE": store}
    run("nix-store", "--store", store, "--load-db", input=registration, env=env)
    registered = subprocess.check_output(
        ["nix-store", "--store", store, "--query", "--requisites", str(system)],
        env=env, text=True).splitlines()
    if sorted(set(registered)) != closure:
        raise RuntimeError("registered closure differs from the installation closure")
    # Verify actual files in the destination against their NAR hashes.
    run("nix-store", "--store", store, "--verify", "--check-contents", env=env,
        stdout=(output / "store-verify.log").open("w"), stderr=subprocess.STDOUT)
    # --load-db records wall-clock time. Normalize only the isolated target DB
    # after verification, so identical inputs can produce identical archives.
    db = sqlite3.connect(stage / "nix/var/nix/db/db.sqlite")
    try:
        db.execute("UPDATE ValidPaths SET registrationTime = 1")
        db.commit()
        db.execute("VACUUM")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    finally:
        db.close()
    profiles = stage / "nix/var/nix/profiles"
    (profiles / "system-1-link").symlink_to(system)
    (profiles / "system").symlink_to("system-1-link")
    (stage / "nix/var/nix/gcroots/profiles").symlink_to("/nix/var/nix/profiles")
    for path in ("init", "sbin/init"):
        (stage / path).symlink_to("/nix/var/nix/profiles/system/init")
    (stage / "etc/y700-rootfs-contract").write_text("tb322fc-rootfs-v1\n")
    (stage / "tmp").chmod(0o1777)
    (stage / "root").chmod(0o700)
    archive = output / "nixos-rootfs.tar.gz"
    command = ["tar", "--sort=name", "--mtime=@0", "--format=posix",
               "--pax-option=delete=atime,delete=ctime", "--owner=0", "--group=0",
               "--numeric-owner", "--xattrs", "--acls", "-C", str(stage), "-cf", "-", "."]
    with archive.open("xb") as target:
        tar = subprocess.Popen(command, stdout=subprocess.PIPE)
        try:
            gzip = subprocess.run(["gzip", "-n", "-1"], stdin=tar.stdout, stdout=target)
        finally:
            tar.stdout.close()
        tar_status = tar.wait()
        if gzip.returncode or tar_status:
            raise RuntimeError(f"archive failed: tar={tar_status}, gzip={gzip.returncode}")
    metadata = {
        "scope": "offline install candidate; no tablet storage writes",
        "system": str(system), "closure_paths": len(closure),
        "nixpkgs": json.loads((PROJECT / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"],
        "kernel": json.loads((PROJECT / "vendor/tb322fc-linux/sources.json").read_text())["kernel"],
        "registration_sha256": hashlib.sha256(registration).hexdigest(),
        "archive_sha256": digest(archive), "archive_bytes": archive.stat().st_size,
        "profile": args.profile,
        "rootfs_type": "btrfs" if args.profile == "persistent" else "ext4",
        "account_policy": ("locked initial y700 password, attended development autologin"
                           if args.profile == "persistent" else "disposable development rootfs"),
        "diagnostics": "trusted-host USB SSH development policy remains; not a release image",
        "source_sha256": {str(path.relative_to(PROJECT)): digest(path) for path in [
            PROJECT / "flake.nix", PROJECT / "flake.lock", PROJECT / "nixos/persistent.nix",
            PROJECT / "nix/profiles/y700-persistent.nix",
            Path(__file__).resolve(),
        ]},
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(f"{metadata['archive_sha256']}  {archive.name}\n")
    print(f"Registered and verified {len(closure)} store paths; archive: {archive}", flush=True)


if __name__ == "__main__":
    main()
