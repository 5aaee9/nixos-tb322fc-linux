#!/usr/bin/env python3
"""Assemble verified board generations into a local FAT image; never install it."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("efi_generation", PROJECT / "tools/build-efi-generation.py")
generation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generation)
require, sha = generation.require, generation.sha
FILES = ("linux.efi", "elden.dtb", "initrd.gz", "options", "boot.json",
         "system-path", "generation-number")


def verify_generation(directory):
    meta = json.loads((directory / "metadata.json").read_text())
    require(meta["schema"] == 1 and set(meta["files"]) == set(FILES), "Unknown generation schema")
    number, system = meta["generation"], meta["system"]
    require(type(number) is int and 0 < number < 2**31, "Invalid generation")
    for name in FILES:
        require((directory / name).is_file() and not (directory / name).is_symlink(),
                "Bundle files must be regular files")
        require(sha(directory / name) == meta["files"][name], "Bundle checksum: " + name)
    expected_kernel = json.loads((generation.VENDOR / "sources.json").read_text())["kernel"]
    require(meta["kernel"]["kernel"] == expected_kernel, "Bundle kernel source pin mismatch")
    require(meta["kernel"]["files"]["Image"] == meta["files"]["linux.efi"] and
            meta["kernel"]["files"]["elden.dtb"] == meta["files"]["elden.dtb"],
            "Bundle kernel/DTB differs from the verified kernel")
    require(meta["firmware_manifest_sha256"] == sha(generation.VENDOR / "firmware-tb322fc-prc.json"),
            "Bundle firmware manifest mismatch")
    require(meta["nixpkgs"] == json.loads((PROJECT / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"],
            "Bundle nixpkgs pin mismatch")
    namespace = generation.esp_namespace(number, meta["files"]["linux.efi"],
                                         meta["files"]["initrd.gz"], meta["files"]["elden.dtb"])
    require(meta["esp_namespace"] == namespace, "Unexpected ESP namespace")
    require(generation.pe_machine(directory / "linux.efi") == 0xaa64, "Not ARM64 EFI")
    require((directory / "elden.dtb").read_bytes()[:4] == b"\xd0\x0d\xfe\xed", "Invalid DTB")
    require((directory / "system-path").read_text() == system + "\n", "System mismatch")
    require((directory / "generation-number").read_text() == str(number) + "\n", "Generation mismatch")
    options = (directory / "options").read_text()
    require(options == generation.command_line(
        system, number, "y700.usb-debug=1" in options.split()) + "\n", "Unexpected kernel options")
    bootspec = json.loads((directory / "boot.json").read_text())
    board, nixos = bootspec["org.y700.board.v1"], bootspec["org.nixos.bootspec.v1"]
    require(nixos["toplevel"] == system and nixos["init"] == system + "/init" and
            nixos["system"] == "aarch64-linux" and nixos["kernelParams"] == options.split(),
            "Bootspec selection mismatch")
    require(nixos["kernel"] == f"/boot/{namespace}/linux.efi" and
            nixos["initrd"] == f"/boot/{namespace}/initrd.gz" and
            board["dtb"] == f"/boot/{namespace}/elden.dtb" and board["generation"] == number,
            "Bootspec target path mismatch")
    return meta


def select_generations(directories, default):
    result = {}
    for directory in directories:
        meta = verify_generation(directory)
        number = meta["generation"]
        require(number not in result, "Duplicate generation")
        result[number] = (directory, meta)
    require(default in result, "Default generation is absent")
    return result


def bls_entry(meta, options):
    namespace, number = meta["esp_namespace"], meta["generation"]
    return (f"title NixOS Y700 generation {number}\nversion {number}\nsort-key nixos\n"
            f"linux /{namespace}/linux.efi\ninitrd /{namespace}/initrd.gz\n"
            f"devicetree /{namespace}/elden.dtb\noptions {options.strip()}\n")


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation", action="append", required=True, type=Path)
    parser.add_argument("--default", type=int, required=True)
    parser.add_argument("--tools", type=Path, default=PROJECT / "result-efi-lab-tools")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    output, tools = args.out.absolute(), args.tools.resolve(strict=True)
    require(not output.exists(), "Output must be a new directory")
    bundles = select_generations([p.resolve(strict=True) for p in args.generation], args.default)
    loader = tools / "systemd/lib/systemd/boot/efi/systemd-bootaa64.efi"
    require(generation.pe_machine(loader) == 0xaa64, "Loader must be ARM64 EFI")
    # The local tool link is produced from the stable nixpkgs pin. Bind the
    # loader as well, so a replaced link cannot silently change the candidate.
    require(sha(loader) == "24387f53badcdc40126e9ffa0a98432a163b011bf9d52d765d99c745c09b5f88",
            "Pinned systemd-boot checksum changed; review the new loader first")
    output.mkdir(parents=True)
    tree = output / "tree"
    for name in ("EFI/BOOT", "EFI/nixos", "loader/entries"):
        (tree / name).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(loader, tree / "EFI/BOOT/BOOTAA64.EFI")
    (tree / "loader/loader.conf").write_text(
        f"default nixos-generation-{args.default}.conf\ntimeout 5\neditor no\n"
        "auto-entries no\nauto-firmware no\n")
    for number, (directory, meta) in sorted(bundles.items()):
        target = tree / meta["esp_namespace"]
        target.mkdir()
        for name in ("linux.efi", "initrd.gz", "elden.dtb", "boot.json"):
            shutil.copyfile(directory / name, target / name)
        (tree / f"loader/entries/nixos-generation-{number}.conf").write_text(
            bls_entry(meta, (directory / "options").read_text()))
    image = output / "esp.img"
    with image.open("xb") as stream:
        stream.truncate(1 << 30)
    run([tools / "dosfstools/bin/mkfs.fat", "--invariant", "-F", "32", "-S", "4096",
         "-s", "1", "-n", "Y700ESP", image])
    env = os.environ | {"MTOOLSRC": "/dev/null"}
    mtools = tools / "mtools/bin"
    run([mtools / "mcopy", "-s", "-i", image, tree / "EFI", tree / "loader", "::/"], env=env)
    files = {str(p.relative_to(tree)): sha(p) for p in sorted(tree.rglob("*")) if p.is_file()}
    # Read every file back through FAT rather than trusting the copy operation.
    import hashlib
    for name, expected in files.items():
        result = subprocess.check_output([str(mtools / "mtype"), "-i", str(image),
                                          "::/" + name], env=env)
        require(hashlib.sha256(result).hexdigest() == expected, "FAT readback: " + name)
    with image.open("rb") as stream:
        require(struct.unpack_from("<H", stream.read(512), 11)[0] == 4096, "FAT sector size")
    run([tools / "dosfstools/bin/fsck.fat", "-n", image])
    evidence = {
        "schema": 1, "scope": "offline ESP candidate only; no tablet write or OpenABL acceptance",
        "bytes": 1 << 30, "sector_bytes": 4096, "default_generation": args.default,
        "generations": {number: {"system": meta["system"], "namespace": meta["esp_namespace"],
                                 "metadata_sha256": sha(directory / "metadata.json")}
                        for number, (directory, meta) in sorted(bundles.items())},
        "nixpkgs": json.loads((PROJECT / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"],
        "image_sha256": sha(image), "files": files, "fat_readback_verified": True,
        "builder_sha256": sha(Path(__file__).resolve()),
    }
    (output / "metadata.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(f"{evidence['image_sha256']}  esp.img\n")
    print(f"Prepared offline ESP with generations {sorted(bundles)}: {output}")


if __name__ == "__main__":
    main()
