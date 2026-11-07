import base64
import copy
import importlib.util
from pathlib import Path
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("evidence", PROJECT / "tools/verify-uefi-nixos.py")
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)
SYSTEM = "/nix/store/" + "1" * 32 + "-nixos-system-fixture"
SYSTEMD = "/nix/store/" + "2" * 32 + "-systemd-260.5/lib/systemd/systemd"
BOOT_ID = "11111111-2222-3333-4444-555555555555"


def encode(text):
    if isinstance(text, str):
        text = text.encode()
    return base64.b64encode(text).decode()


def efi(value):
    return encode(b"\x07\0\0\0" + value.encode("utf-16-le") + b"\0\0")


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        names, rows = [], []
        for index, letter in enumerate("abcdef"):
            for part in (0, 1):
                name = "sd" + letter + (str(part) if part else "")
                names.append(name)
                label = "rootfs" if index == 0 and part == 1 else ""
                rows.append(f"{name}\t8:{index * 16 + part}\t1\t{part}\t{label}")
        self.expected = {
            "challenge": "a" * 32, "previous_boot_id": "99999999-2222-3333-4444-555555555555",
            "ufs_names": names, "system": SYSTEM, "generation": 2,
            "kernel": "7.2.0-y700-efi", "loader": "systemd-boot 260.5",
            "systemd_exe": SYSTEMD, "desktop_user": "fixture-user",
        }
        mounts = "\n".join([
            "10 1 0:20 / / rw,relatime - overlay overlay rw,lowerdir=/run/y700-root/lower,"
            "upperdir=/run/y700-root/overlay/upper,workdir=/run/y700-root/overlay/work",
            "11 10 8:1 / /run/y700-root/lower ro,relatime - ext4 /dev/sda1 ro,norecovery",
            "12 10 0:21 / /run/y700-root/overlay rw,nosuid,nodev - tmpfs rootfs-overlay rw,size=2097152k",
            "13 10 0:22 / /proc rw,nosuid,nodev,noexec - proc proc rw",
        ])
        self.raw = {
            "boot_id_start": BOOT_ID, "boot_id_end": BOOT_ID,
            "efi_platform": "64", "provider_base64": encode(b"ram-v1\0"),
            "loader_base64": efi(self.expected["loader"]),
            "entry_base64": efi("nixos-generation-2.conf"), "kernel": self.expected["kernel"],
            "current_system": SYSTEM, "pid1_exe": SYSTEMD,
            "cmdline": f"root=PARTLABEL=rootfs rdinit=/init init={SYSTEM}/init "
                       f"y700.system={SYSTEM} y700.generation=2 y700.usb-debug=1",
            "root_mode": "readonly-overlay",
            "blocks_start": "\n".join(rows), "blocks_end": "\n".join(rows),
            "mounts_start": mounts, "mounts_end": mounts,
            "display_manager": "ActiveState=active\nSubState=running\nMainPID=100",
            "sshd": "ActiveState=active\nSubState=running",
            "failed_units": "",
            "processes": "1 0 systemd\n100 0 gdm\n101 1000 gnome-shell",
            "sessions": "1 1000 fixture-user seat0 101 user tty2 no -",
            "session.1": "Id=1\nUser=1000\nName=fixture-user\nClass=user\nType=wayland\n"
                         "Active=yes\nState=active\nRemote=no\nService=gdm-autologin",
        }

    def wire(self, raw=None, statuses=None):
        raw = self.raw if raw is None else raw
        lines = ["Y700_EFI_NIXOS_EVIDENCE_V1\t" + self.expected["challenge"]]
        lines.extend(f"{key}\t{(statuses or {}).get(key, 0)}\t{encode(value)}"
                     for key, value in raw.items())
        lines.append("Y700_EFI_NIXOS_EVIDENCE_END")
        return ("\n".join(lines) + "\n").encode()

    def report(self, raw=None, statuses=None):
        return evidence.assess(self.wire(raw, statuses), self.expected)

    def rejected(self, key, raw=None, statuses=None):
        report = self.report(raw, statuses)
        self.assertFalse(report["machine_acceptance_passed"])
        self.assertFalse(report["checks"][key], report)
        return report

    def test_complete_fixture_keeps_physical_confirmation_separate(self):
        report = self.report()
        self.assertTrue(report["machine_acceptance_passed"], report)
        self.assertEqual(report["physical_desktop_confirmation"], "still required")
        self.assertFalse(report["gnome_greeter_session"])

    def test_unfinished_execution_expectations_are_rejected(self):
        for key in ("challenge", "previous_boot_id"):
            for value in (None, "", "FRESH_PREFLIGHT_REQUIRED"):
                with self.subTest(key=key, value=value):
                    expected = self.expected | {key: value}
                    with self.assertRaises(ValueError):
                        evidence.assess(self.wire(), expected)

    def test_greeter_is_not_a_logged_in_desktop(self):
        self.raw["session.1"] = self.raw["session.1"].replace("Class=user", "Class=greeter")
        report = self.rejected("gnome_desktop")
        self.assertTrue(report["checks"]["gdm_running"])
        self.assertTrue(report["gnome_greeter_session"])

    def test_degraded_units_do_not_hide_successful_chain(self):
        self.raw["failed_units"] = "systemd-remount-fs.service loaded failed failed Remount"
        report = self.rejected("no_failed_units")
        self.assertTrue(report["checks"]["efi_nixos_chain"])
        self.assertTrue(report["checks"]["readonly_storage"])
        self.assertIn("systemd-remount-fs", report["failed_units"]["output"])

    def test_missing_or_failed_commands_cannot_pass(self):
        for key, group in (("efi_platform", "efi_nixos_chain"), ("blocks_start", "readonly_storage"),
                           ("display_manager", "gdm_running"), ("sessions", "gnome_desktop"),
                           ("failed_units", "no_failed_units"), ("sshd", "ssh_running")):
            with self.subTest(key=key):
                raw = copy.deepcopy(self.raw)
                del raw[key]
                self.rejected(group, raw)
                self.rejected(group, statuses={key: 124})

    def test_duplicate_command_line_selection_is_rejected(self):
        for addition in ("root=PARTLABEL=rootfs", "y700.generation=2",
                         "y700.system=" + SYSTEM, "init=" + SYSTEM + "/init"):
            with self.subTest(addition=addition):
                raw = self.raw | {"cmdline": self.raw["cmdline"] + " " + addition}
                self.rejected("efi_nixos_chain", raw)

    def test_wrong_chain_and_changed_or_old_boot_are_rejected(self):
        cases = {
            "kernel": "wrong", "current_system": SYSTEM + "-other", "pid1_exe": "/wrong",
            "efi_platform": "32", "provider_base64": encode(b"other\0"),
            "loader_base64": efi("other loader"), "entry_base64": efi("y700-efi-diag.conf"),
            "boot_id_end": self.expected["previous_boot_id"],
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                self.rejected("efi_nixos_chain", self.raw | {key: value})
        self.expected["previous_boot_id"] = BOOT_ID
        self.rejected("efi_nixos_chain")

    def test_writable_missing_extra_and_duplicate_block_nodes_are_rejected(self):
        baseline = self.raw["blocks_start"]
        cases = [
            baseline.replace("sda\t8:0\t1", "sda\t8:0\t0"),
            "\n".join(baseline.splitlines()[1:]),
            baseline + "\nsdg\t8:96\t1\t0\t",
            baseline + "\n" + baseline.splitlines()[0],
            baseline.replace("rootfs", "absent"),
            baseline.replace("sdb1\t8:17\t1\t1\t", "sdb1\t8:17\t1\t1\trootfs"),
        ]
        for text in cases:
            with self.subTest(text=text):
                self.rejected("readonly_storage", self.raw | {"blocks_start": text, "blocks_end": text})

    def test_block_or_mount_changes_are_rejected(self):
        self.rejected("readonly_storage", self.raw | {"blocks_end": self.raw["blocks_end"] + "\n"})
        self.rejected("readonly_storage", self.raw | {"mounts_end": self.raw["mounts_end"] + "\n"})

    def test_rootfs_must_belong_to_the_frozen_ufs_inventory(self):
        nodes = self.raw["blocks_start"].replace("rootfs", "") + "\nloop0p1\t259:1\t0\t1\trootfs"
        mounts = self.raw["mounts_start"].replace("11 10 8:1", "11 10 259:1")
        self.rejected("readonly_storage", self.raw | {
            "blocks_start": nodes, "blocks_end": nodes,
            "mounts_start": mounts, "mounts_end": mounts,
        })

    def test_anonymous_physical_or_unclassified_filesystems_cannot_pass(self):
        baseline = self.raw["mounts_start"]
        for filesystem, source in (
                ("btrfs", "/dev/sdb1"), ("fuse", "/dev/sdb1"),
                ("fuseblk", "/dev/sdb1"), ("fuse.somefs", "none"),
                ("ext4", "/dev/sdb1"), ("unknown", "none")):
            with self.subTest(filesystem=filesystem):
                mounts = baseline + f"\n14 10 0:39 / /extra ro - {filesystem} {source} ro"
                self.rejected("readonly_storage", self.raw | {
                    "mounts_start": mounts, "mounts_end": mounts,
                })
        extra = "\n14 10 0:39 / /extra rw - overlay overlay rw,lowerdir=/run/y700-root/lower"
        self.rejected("readonly_storage", self.raw | {
            "mounts_start": baseline + extra, "mounts_end": baseline + extra,
        })

    def test_known_pseudo_mounts_and_root_overlay_binds_are_accepted(self):
        mounts = self.raw["mounts_start"]
        mounts += "\n14 10 0:25 / /sys/fs/cgroup rw - cgroup2 cgroup2 rw"
        overlay_options = mounts.splitlines()[0].split(" - ")[1]
        mounts += "\n15 10 0:20 /nix/store /nix/store ro - " + overlay_options
        self.assertTrue(self.report(self.raw | {"mounts_start": mounts, "mounts_end": mounts})
                        ["checks"]["readonly_storage"])

    def test_unsafe_mount_topologies_are_rejected(self):
        baseline = self.raw["mounts_start"]
        cases = [
            baseline.replace("ro,norecovery", "ro"),
            baseline.replace("lower ro,relatime", "lower rw,relatime"),
            baseline.replace("11 10 8:1", "11 10 8:17"),
            baseline.replace("upperdir=/run/y700-root/overlay/upper", "upperdir=/persistent"),
            baseline.replace("- tmpfs rootfs-overlay", "- ext4 /dev/sdb1"),
            baseline.replace("size=2097152k", "size=4g"),
            baseline + "\n14 10 8:17 / /extra ro - ext4 /dev/sdb1 ro,norecovery",
            baseline + "\n" + baseline.splitlines()[0],
        ]
        for text in cases:
            with self.subTest(text=text):
                self.rejected("readonly_storage", self.raw | {"mounts_start": text, "mounts_end": text})

    def test_noload_and_equivalent_two_gib_limit_are_accepted(self):
        mounts = self.raw["mounts_start"].replace("norecovery", "noload").replace("2097152k", "2g")
        self.assertTrue(self.report(self.raw | {"mounts_start": mounts, "mounts_end": mounts})
                        ["checks"]["readonly_storage"])

    def test_shell_uid_inactive_remote_or_wrong_user_cannot_prove_desktop(self):
        for old, new in (("User=1000", "User=1001"), ("Name=fixture-user", "Name=other"),
                         ("Active=yes", "Active=no"), ("Type=wayland", "Type=tty"),
                         ("Remote=no", "Remote=yes"), ("Id=1", "Id=2")):
            with self.subTest(old=old):
                self.rejected("gnome_desktop",
                              self.raw | {"session.1": self.raw["session.1"].replace(old, new)})
        self.rejected("gnome_desktop", self.raw | {"processes": "1 0 systemd\n100 0 gdm"})

    def test_session_inventory_race_or_duplicate_properties_is_rejected(self):
        self.rejected("gnome_desktop", self.raw | {"sessions": ""})
        self.rejected("gnome_desktop", self.raw | {"session.1": self.raw["session.1"] + "\nId=1"})

    def test_malformed_or_truncated_transport_is_rejected(self):
        wire = self.wire()
        for data in (
            wire.replace(("a" * 32).encode(), b"b" * 32, 1),
            wire.rsplit(b"Y700_EFI_NIXOS_EVIDENCE_END", 1)[0],
            wire.replace(b"kernel\t0\t", b"kernel\t-1\t", 1),
            wire.replace(b"kernel\t0\t", b"kernel\t0\t!\t", 1),
            wire.replace(b"Y700_EFI_NIXOS_EVIDENCE_END", b"kernel\t0\tYQ==\nY700_EFI_NIXOS_EVIDENCE_END"),
        ):
            with self.subTest(data=data[:80]), self.assertRaises(ValueError):
                evidence.records(data, self.expected["challenge"])


if __name__ == "__main__":
    unittest.main()
