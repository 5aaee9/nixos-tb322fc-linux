#!/usr/bin/env python3
"""Assess saved RAM-UEFI NixOS evidence; never connect to or change a device."""
import argparse
import base64
import binascii
import json
from pathlib import Path
import re

LIMIT = 8 * 1024 * 1024
DISKS = {f"sd{letter}" for letter in "abcdef"}
PSEUDO_FILESYSTEMS = {
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "configfs", "debugfs",
    "devpts", "devtmpfs", "efivarfs", "fusectl", "hugetlbfs", "mqueue", "proc",
    "pstore", "ramfs", "rootfs", "securityfs", "sysfs", "tmpfs", "tracefs",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode64(value):
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Invalid base64 evidence") from error


def records(data, challenge):
    require(len(data) <= LIMIT, "Evidence exceeds size limit")
    lines = data.decode("ascii").splitlines()
    require(lines and lines[0] == "Y700_EFI_NIXOS_EVIDENCE_V1\t" + challenge,
            "Missing or stale evidence challenge")
    require(lines[-1] == "Y700_EFI_NIXOS_EVIDENCE_END", "Incomplete evidence")
    result = {}
    for line in lines[1:-1]:
        parts = line.split("\t")
        require(len(parts) == 3, "Invalid evidence record")
        key, status, encoded = parts
        require(re.fullmatch(r"[a-z][a-zA-Z0-9_.-]*", key), "Invalid record key")
        require(key not in result and re.fullmatch(r"[0-9]{1,3}", status),
                "Duplicate record or invalid exit status")
        result[key] = {"status": int(status), "output": decode64(encoded).decode("utf-8")}
    return result


def properties(text):
    result = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        require(sep and key and key not in result, "Invalid or duplicate property")
        result[key] = value
    return result


def mounts(text):
    result = []
    for line in text.splitlines():
        fields = line.split()
        require("-" in fields, "Invalid mountinfo record")
        split = fields.index("-")
        require(split >= 6 and len(fields) == split + 4, "Invalid mountinfo fields")
        result.append({
            "device": fields[2], "root": fields[3], "target": fields[4],
            "options": set(fields[5].split(",")), "type": fields[split + 1],
            "source": fields[split + 2], "super": set(fields[split + 3].split(",")),
        })
    return result


def blocks(text):
    result = {}
    devices = set()
    for line in text.splitlines():
        parts = line.split("\t")
        require(len(parts) == 5, "Invalid block record")
        name, device, readonly, partition, label = parts
        require(re.fullmatch(r"[a-zA-Z0-9_-]+", name), "Invalid block name")
        require(name not in result and device not in devices, "Duplicate block identity")
        require(re.fullmatch(r"[0-9]+:[0-9]+", device), "Invalid block device number")
        require(readonly in ("0", "1") and partition.isdecimal(), "Invalid block state")
        result[name] = {"device": device, "readonly": readonly,
                        "partition": int(partition), "label": label}
        devices.add(device)
    return result


def efi_string(encoded):
    raw = decode64("".join(encoded.splitlines()))
    require(len(raw) >= 6 and len(raw[4:]) % 2 == 0, "Invalid EFI variable")
    text = raw[4:].decode("utf-16-le")
    require(text.endswith("\0") and "\0" not in text[:-1], "Invalid EFI string")
    return text[:-1]


def assess(data, expected):
    require(isinstance(expected["challenge"], str) and
            re.fullmatch(r"[0-9a-f]{32}", expected["challenge"]), "Invalid challenge")
    require(isinstance(expected["previous_boot_id"], str) and
            re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                         expected["previous_boot_id"]), "Invalid previous boot ID")
    names = expected["ufs_names"]
    require(len(names) == len(set(names)) and DISKS.issubset(names),
            "Expected inventory lacks unique UFS disks")
    require(all(re.fullmatch(r"sd[a-f](?:[1-9][0-9]*)?", name) for name in names),
            "Invalid expected UFS inventory")
    require(type(expected["generation"]) is int and expected["generation"] > 0,
            "Invalid expected generation")
    require(re.fullmatch(r"/nix/store/[0-9a-df-np-sv-z]{32}-nixos-system-[A-Za-z0-9.+_-]+",
                        expected["system"]), "Invalid expected system")
    evidence = records(data, expected["challenge"])
    failures = {}

    def text(key):
        require(key in evidence, "Missing record: " + key)
        require(evidence[key]["status"] == 0, "Command failed: " + key)
        return evidence[key]["output"]

    def check(name, function):
        try:
            function()
            return True
        except (ValueError, KeyError, UnicodeError) as error:
            failures[name] = str(error)
            return False

    def chain():
        boot_id = text("boot_id_start")
        require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot_id),
                "Invalid Linux boot ID")
        require(boot_id == text("boot_id_end") and boot_id != expected["previous_boot_id"],
                "Boot changed during collection or evidence is stale")
        require(text("efi_platform") == "64", "Not a 64-bit EFI boot")
        require(decode64(text("provider_base64")) == b"ram-v1\0", "Wrong provider")
        require(efi_string(text("loader_base64")) == expected["loader"], "Wrong EFI loader")
        require(efi_string(text("entry_base64")) ==
                f"nixos-generation-{expected['generation']}.conf", "Wrong EFI entry")
        require(text("kernel") == expected["kernel"], "Wrong kernel release")
        require(text("current_system") == expected["system"], "Wrong active NixOS system")
        require(text("pid1_exe") == expected["systemd_exe"], "Wrong PID 1 executable")
        options = text("cmdline").split()
        for prefix, wanted in (
            ("y700.system=", expected["system"]),
            ("y700.generation=", str(expected["generation"])),
            ("init=", expected["system"] + "/init"),
            ("root=", "PARTLABEL=rootfs"),
        ):
            require([x for x in options if x.startswith(prefix)] == [prefix + wanted],
                    "Ambiguous or wrong command-line selection: " + prefix)

    def storage():
        require(text("root_mode") == "readonly-overlay", "Not the RAM-overlay handoff")
        require(text("blocks_start") == text("blocks_end"), "Block state changed during collection")
        require(text("mounts_start") == text("mounts_end"), "Mounts changed during collection")
        inventory = blocks(text("blocks_start"))
        actual = {name for name in inventory if re.fullmatch(r"sd[a-z]+[0-9]*", name)}
        require(actual == set(names), "UFS inventory differs from frozen baseline")
        require(all(inventory[name]["readonly"] == "1" for name in actual), "Writable UFS node")
        require(all(inventory[name]["partition"] == 0 for name in DISKS), "UFS disk mismatch")
        roots = [(name, item) for name, item in inventory.items()
                 if item["partition"] > 0 and item["label"] == "rootfs"]
        require(len(roots) == 1, "Missing or ambiguous physical rootfs")
        root_name, root_block = roots[0]
        require(root_name in actual, "Rootfs is outside the frozen UFS inventory")
        table = mounts(text("mounts_start"))

        def at(target):
            matches = [item for item in table if item["target"] == target]
            require(len(matches) == 1, "Missing or stacked mount: " + target)
            return matches[0]

        root, lower, upper = at("/"), at("/run/y700-root/lower"), at("/run/y700-root/overlay")
        require(root["type"] == "overlay" and "rw" in root["options"], "Root is not an overlay")
        require({"lowerdir=/run/y700-root/lower", "upperdir=/run/y700-root/overlay/upper",
                 "workdir=/run/y700-root/overlay/work"}.issubset(root["super"]),
                "Overlay directories differ")
        require(lower["type"] == "ext4" and lower["device"] == root_block["device"] and
                lower["root"] == "/", "Lower root does not map to rootfs")
        require("ro" in lower["options"] and "rw" not in lower["options"] and
                "ro" in lower["super"] and bool({"noload", "norecovery"} & lower["super"]),
                "Lower root permits writes or journal replay")
        require(upper["type"] == "tmpfs" and "rw" in upper["options"], "Upper is not RAM")
        sizes = [x[5:] for x in upper["super"] if x.startswith("size=")]
        require(len(sizes) == 1, "Missing tmpfs size limit")
        match = re.fullmatch(r"([0-9]+)([kmg]?)", sizes[0])
        require(match is not None, "Invalid tmpfs size")
        size = int(match[1]) * (1024 ** ("", "k", "m", "g").index(match[2]))
        require(0 < size <= 2 * 1024 ** 3, "Overlay exceeds 2 GiB limit")
        # Btrfs and FUSE can use anonymous (major-zero) device numbers.
        # Accept known pseudo/desktop mounts and binds of this root overlay.
        require(root["device"].startswith("0:") and upper["device"].startswith("0:"),
                "Overlay or tmpfs has an unexpected device number")
        for item in table:
            if item == lower:
                continue
            require(item["device"].startswith("0:"), "Another physical filesystem is mounted")
            if item["type"] == "overlay":
                require(item["device"] == root["device"] and
                        item["source"] == root["source"] and item["super"] == root["super"],
                        "Another overlay filesystem is mounted")
            elif item["type"] in ("fuse.gvfsd-fuse", "fuse.portal"):
                uid = expected.get("desktop_uid")
                require(type(uid) is int and uid > 0, "Missing desktop UID for GNOME mount")
                source, suffix = {
                    "fuse.gvfsd-fuse": ("gvfsd-fuse", "gvfs"),
                    "fuse.portal": ("portal", "doc"),
                }[item["type"]]
                require(item["source"] == source and item["root"] == "/" and
                        item["target"] == f"/run/user/{uid}/{suffix}" and
                        f"user_id={uid}" in item["super"] and
                        {"nosuid", "nodev"}.issubset(item["options"]),
                        "GNOME virtual mount has unexpected ownership or location")
            else:
                require(item["type"] in PSEUDO_FILESYSTEMS,
                        "Unclassified filesystem is mounted: " + item["type"])

    def service(key):
        state = properties(text(key))
        require(state.get("ActiveState") == "active" and state.get("SubState") == "running",
                "Service is not running: " + key)
        if key == "display_manager":
            require(state.get("MainPID", "").isdecimal() and int(state["MainPID"]) > 1,
                    "Display manager lacks a live PID")

    def desktop(session_class):
        listed = [line.split()[0] for line in text("sessions").splitlines() if line.split()]
        require(len(listed) <= 8 and len(listed) == len(set(listed)), "Invalid session inventory")
        require({key[8:] for key in evidence if key.startswith("session.")} == set(listed),
                "Session table and details differ")
        shell_users = set()
        if "process_executables" in evidence:
            shell_exe = expected.get("gnome_shell_exe", "")
            require(re.fullmatch(
                r"/nix/store/[0-9a-df-np-sv-z]{32}-gnome-shell-[^/\s]+/bin/"
                r"(?:gnome-shell|\.gnome-shell-wrapped)", shell_exe),
                "Missing or invalid expected GNOME executable")
            for line in text("process_executables").splitlines():
                fields = line.split("\t")
                require(len(fields) == 3 and fields[0].isdecimal() and fields[1].isdecimal(),
                        "Invalid executable record")
                if fields[2] == shell_exe:
                    shell_users.add(fields[1])
        else:
            # Retain support for older captures without executable evidence.
            for line in text("processes").splitlines():
                fields = line.split(None, 2)
                require(len(fields) == 3 and fields[0].isdecimal() and fields[1].isdecimal(),
                        "Invalid process record")
                if fields[2] == "gnome-shell":
                    shell_users.add(fields[1])
        details_by_session = {session: properties(text("session." + session)) for session in listed}
        for session, details in details_by_session.items():
            require(details.get("Id") == session, "Session identity differs")
        for details in details_by_session.values():
            if (details.get("Class") == session_class and details.get("Type") == "wayland"
                    and details.get("Active") == "yes" and details.get("State") == "active"
                    and details.get("Remote") == "no" and details.get("User") in shell_users
                    and (session_class != "user" or details.get("Name") == expected["desktop_user"])):
                return
        raise ValueError("No active GNOME Wayland " + session_class + " session")

    checks = {
        "efi_nixos_chain": check("efi_nixos_chain", chain),
        "readonly_storage": check("readonly_storage", storage),
        "gdm_running": check("gdm_running", lambda: service("display_manager")),
        "ssh_running": check("ssh_running", lambda: service("sshd")),
        "no_failed_units": check("no_failed_units",
                                 lambda: require(not text("failed_units").strip(), "Failed system units")),
        "gnome_desktop": check("gnome_desktop", lambda: desktop("user")),
    }
    try:
        desktop("greeter")
        greeter = True
    except (ValueError, KeyError, UnicodeError):
        greeter = False
    return {
        "schema": 1, "checks": checks, "failures": failures,
        "gnome_greeter_session": greeter,
        "machine_acceptance_passed": all(checks.values()),
        "physical_desktop_confirmation": "still required",
        "failed_units": evidence.get("failed_units"),
        "boot_id": evidence.get("boot_id_start"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    args = parser.parse_args()
    with args.evidence.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    try:
        report = assess(data, json.loads(args.expected.read_text()))
    except (ValueError, KeyError, UnicodeError) as error:
        report = {"machine_acceptance_passed": False, "invalid_evidence": str(error)}
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["machine_acceptance_passed"] else 1)


if __name__ == "__main__":
    main()
