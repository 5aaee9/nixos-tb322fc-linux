#!/usr/bin/env python3
"""Check the complete pinned OpenABL sources without resetting a worktree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

PINS = {
    ".": "59338daddd4be82712e2e72bf15cd2f480d517b4",
    "build/edk2": "aef4e86045bd151a54d33bab8ae5e8e62462a8f4",
    "build/microui": "0850aba860959c3e75fb3e97120ca92957f9d057",
    "build/qtestsign": "f3df53a5f0e37ccee076541f30f9d5b8340fc2d3",
}
LOCAL_PATCHES = (
    "0001-fix-no-standard-boot-unused-variable.patch",
    "0002-edk2-native-response-quotes.patch",
    "0003-edk2-avb-result-enum.patch",
    "0004-edk2-reject-unresolved-verity-mode.patch",
    "0005-add-no-storage-entry-probe.patch",
)
PREBUILT = "QcomModulePkg/Prebuilt/OpenAblMenu/openabl-menu.efi"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args, **kwargs):
    return subprocess.check_output(["git", "-C", str(repo), *args], **kwargs)


def pinned_files(repo, pin):
    require(git(repo, "rev-parse", "HEAD").decode().strip() == pin,
            f"Wrong source pin: {repo}")
    entries = {}
    for entry in git(repo, "ls-tree", "-rz", pin).split(b"\0"):
        if entry:
            info, name = entry.split(b"\t", 1)
            mode, kind, oid = info.decode().split()
            require(kind in ("blob", "commit"), f"Unsupported Git entry: {name!r}")
            entries[name.decode()] = (mode, oid)
    ids = sorted({oid for mode, oid in entries.values() if mode != "160000"})
    raw = git(repo, "cat-file", "--batch", input=("".join(x + "\n" for x in ids)).encode())
    blobs, offset = {}, 0
    for oid in ids:
        end = raw.index(b"\n", offset)
        actual, kind, size = raw[offset:end].decode().split()
        require(actual == oid and kind == "blob", "Unexpected Git object")
        offset = end + 1
        blobs[oid] = raw[offset:offset + int(size)]
        offset += int(size) + 1
    files = {name: (mode, oid.encode() if mode == "160000" else blobs[oid])
             for name, (mode, oid) in entries.items()}
    # The pinned lz4 subtree explicitly checks Visual Studio files out as CRLF.
    # Ask for attributes from the commit, never from the modified working tree.
    attributes = git(repo, "-c", "core.attributesFile=/dev/null", "check-attr",
                     "--source=" + pin, "-z", "--stdin", "eol",
                     input=b"".join(name.encode() + b"\0" for name in files)).split(b"\0")
    for index in range(0, len(attributes) - 1, 3):
        name, _, eol = attributes[index:index + 3]
        mode, data = files[name.decode()]
        if mode in ("100644", "100755") and eol in (b"lf", b"crlf"):
            data = data.replace(b"\r\n", b"\n")
            if eol == b"crlf":
                data = data.replace(b"\n", b"\r\n")
            files[name.decode()] = (mode, data)
    return files


def apply_expected_patches(files, patches):
    """Reconstruct only patch-touched files in an isolated temporary directory."""
    result = dict(files)
    with tempfile.TemporaryDirectory(prefix="y700-openabl-source-check-") as temp:
        directory = Path(temp)
        touched = set()
        for patch in patches:
            for item in git(directory, "apply", "--numstat", "-z", str(patch)).split(b"\0"):
                if item:
                    name = item.split(b"\t", 2)[2].decode()
                    require(name in files and files[name][0] in ("100644", "100755"),
                            f"Patch must modify an existing regular source: {name}")
                    if name not in touched:
                        target = directory / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(files[name][1])
                        target.chmod(0o755 if files[name][0] == "100755" else 0o644)
                        touched.add(name)
            subprocess.run(["git", "-C", temp, "apply", "--whitespace=nowarn", str(patch)],
                           check=True)
        for name in touched:
            result[name] = (files[name][0], (directory / name).read_bytes())
    return result


def actual_file(repo, name, mode):
    path = repo / name
    require(all(not p.is_symlink() for p in path.parents if p != repo and repo in p.parents),
            f"Symlink source parent: {name}")
    require(path.exists() or path.is_symlink(), f"Missing source: {name}")
    if mode == "160000":
        require(path.is_dir() and not path.is_symlink() and not any(path.iterdir()),
                f"Unused submodule must stay unpopulated: {name}")
        return None
    if mode == "120000":
        require(path.is_symlink(), f"Source must be a symlink: {name}")
        return os.readlink(path).encode()
    require(path.is_file() and not path.is_symlink(), f"Source must be regular: {name}")
    executable = bool(path.stat().st_mode & stat.S_IXUSR)
    require(executable == (mode == "100755"), f"Source executable mode differs: {name}")
    return path.read_bytes()


def check_files(repo, expected, *, alternatives=None, allow_extra=None):
    alternatives = alternatives or {}
    records, variants = {}, {}
    for name, (mode, data) in sorted(expected.items()):
        actual = actual_file(repo, name, mode)
        if mode != "160000":
            allowed = alternatives.get(name, (data,))
            require(actual in allowed, f"Unreviewed source content: {repo}/{name}")
            if name in alternatives:
                variants[name] = sha(actual)
        records[name] = {"mode": mode, "sha256": sha(data)}
    # Do not honor ignore rules or index assume-unchanged flags as source policy.
    for raw in git(repo, "ls-files", "--cached", "--others", "-z").split(b"\0"):
        if raw:
            name = raw.decode().rstrip("/")
            require(name in expected or (allow_extra and allow_extra(name)),
                    f"Unreviewed extra source: {repo}/{name}")
    return {
        "files": len(records),
        "canonical_sha256": sha(json.dumps(records, sort_keys=True).encode()),
        "configuration_variants": variants,
    }


def build_environment(repo):
    tools = repo / "BaseTools"
    binaries = tools / "Bin/Linux-x86_64"
    return (
        f"# Auto-generated by {tools}/BuildEnv\n"
        'if [ -z "$WORKSPACE" ]\nthen\n'
        f"  export WORKSPACE={repo}\nfi\n"
        'if [ -z "$EDK_TOOLS_PATH" ]\nthen\n'
        f"  export EDK_TOOLS_PATH={tools}\nfi\n"
        f"if [ -e {binaries} ]\nthen\n"
        f"  if [ ${{PATH/{binaries}/}} == $PATH ]\n"
        f"  then\n    export PATH={binaries}:$PATH\n  fi\nfi\n"
    ).encode()


def generated_extra(name, kind):
    parts = Path(name).parts
    if "__pycache__" in parts and name.endswith(".pyc"):
        return True
    if kind == ".":
        return name == "build" or name.startswith("build/")
    if kind == "build/edk2":
        return (name in (PREBUILT, "build_modulepkg.log", "Conf/BuildEnv.sh", "Conf/.AutoGenIdFile.txt",
                         "Conf/.cache/.PlatformBuild")
                or name.startswith("obj/ABL_OBJ/"))
    return False


def verify(project, source, *, menu=None, configured=False):
    patch_dir = project / "vendor/tb322fc-linux/patches/openabl"
    patches = [patch_dir / name for name in LOCAL_PATCHES]
    base = {name: pinned_files(source / name, pin) for name, pin in PINS.items()}
    expected_openabl = apply_expected_patches(base["."], patches[:1])
    openabl_check = check_files(source, expected_openabl,
                               allow_extra=lambda name: generated_extra(name, "."))
    # Only derive the EDK2 overlay after its OpenABL source has passed the pin check.
    expected_edk2 = apply_expected_patches(
        base["build/edk2"], [source / "Abl/openabl.patch", *patches[1:]])
    for name, item in expected_openabl.items():
        if name.startswith("Abl/QcomModulePkg/"):
            expected_edk2[name.removeprefix("Abl/")] = item
    alternatives = {}
    for stem in ("target", "build_rule", "tools_def"):
        name = f"Conf/{stem}.txt"
        template = expected_edk2[f"BaseTools/Conf/{stem}.template"][1]
        alternatives[name] = ((template,) if configured
                              else (base["build/edk2"][name][1], template))
        expected_edk2[name] = (expected_edk2[name][0], template)
    edk2 = source / "build/edk2"
    generated_env = edk2 / "Conf/BuildEnv.sh"
    if generated_env.exists() or generated_env.is_symlink():
        require(actual_file(edk2, "Conf/BuildEnv.sh", "100644") == build_environment(edk2),
                "Unreviewed generated BuildEnv.sh")
    checks = {".": openabl_check}
    checks["build/edk2"] = check_files(
        source / "build/edk2", expected_edk2, alternatives=alternatives,
        allow_extra=lambda name: generated_extra(name, "build/edk2"))
    for name in ("build/microui", "build/qtestsign"):
        checks[name] = check_files(
            source / name, base[name], allow_extra=lambda path: generated_extra(path, name))
    menu_hash = None
    if menu is not None:
        require(menu.is_file() and not menu.is_symlink(), "Menu must be a regular file")
        installed = actual_file(source / "build/edk2", PREBUILT, "100644")
        require(installed == menu.read_bytes(), "Prebuilt menu differs from this build")
        menu_hash = sha(installed)
    inputs = {
        "pins": PINS,
        "sources": {name: item["canonical_sha256"] for name, item in checks.items()},
        "patches": {p.name: sha(p.read_bytes()) for p in patches},
        "generated_build_environment_sha256": sha(build_environment(edk2)),
    }
    return {
        "schema": 1, "scope": "pinned source content; not a hermetic toolchain attestation",
        "inputs": inputs, "input_digest": sha(json.dumps(inputs, sort_keys=True).encode()),
        "checks": checks, "configured": configured, "prebuilt_menu_sha256": menu_hash,
        "verifier_sha256": sha(Path(__file__).read_bytes()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--menu", type=Path)
    parser.add_argument("--configured", action="store_true")
    args = parser.parse_args()
    require(not args.out.exists(), "Verification output must be new")
    report = verify(Path(__file__).resolve().parents[1], args.source.resolve(),
                    menu=args.menu, configured=args.configured)
    if args.previous:
        previous = json.loads(args.previous.read_text())
        require(report["inputs"] == previous["inputs"] and
                report["verifier_sha256"] == previous["verifier_sha256"],
                "Sources, patches or verifier changed during the build")
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Verified complete pinned sources: {report['input_digest']}")


if __name__ == "__main__":
    main()
