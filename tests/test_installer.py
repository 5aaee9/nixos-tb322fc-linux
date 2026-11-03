import base64
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from test_storage_layout import replace_entries, snapshot

PROJECT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, PROJECT / path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


host = module("install_host", "tools/install-nixos.py")
device = module("install_device", "tools/installer/device.py")
SYSTEM = "/nix/store/" + "a" * 32 + "-nixos-system-test"
META = {"system": SYSTEM, "archive_bytes": 100, "closure_paths": 1}


def six_captures():
    result = []
    for i in range(6):
        item = snapshot()
        if i:
            entries = bytearray(base64.b64decode(item["regions"]["primary_entries"]["base64"]))
            entries[128 + 56:128 + 128] = bytes(72)
            label = ("other" + str(i)).encode("utf-16-le")
            entries[128 + 56:128 + 56 + len(label)] = label
            entries[2 * 128 + 56] = ord("x")
            replace_entries(item, entries)
        item.update(controller_lun=f"/sys/mock/ufs/lun{i}", disk_path=f"/dev/sd{chr(97+i)}",
                    system=SYSTEM, boot_id="maintenance-original")
        result.append(item)
    return result


class SimulatedInstaller(host.Installer):
    """Only the coordinator is real. All transports and device actions are fake."""
    def __init__(self, directory, calls, setup_done=False, fail=None):
        config = {"maintenance_system": SYSTEM, "archive": "/unused/test-archive.tar.gz"}
        with patch.object(host, "validate_config", return_value=(META, [SYSTEM])):
            super().__init__(config, directory)
        self.calls = calls
        self.setup_done = setup_done
        self.fail = fail

    def android(self, after=False, wait=False):
        if after and not self.setup_done:
            raise RuntimeError("Android setup needs owner")
        self.calls.append("android-after" if after else "android-original")
        return {"verified": True}

    def boot(self, name, persistent=False, previous=None):
        self.calls.append("boot:" + name)
        return {"name": name}

    def backups(self, session, inspection):
        self.calls.append("backup")
        return {"verified": True}

    def rpc(self, session, action, request, files=None, reboot=False):
        self.calls.append(action)
        if action == self.fail:
            raise RuntimeError("simulated lost response")
        if action == "inspect":
            captures = six_captures()
            if not request["fresh"]:
                captures[0] = self.state["transaction"]["after"]
            return {"boot_id": session["name"], "gpts": captures, "backups": {}}
        if action == "keys":
            return {"sha256": "0" * 64, "bytes": 10}
        if action == "verify":
            if "marker" in request:
                assert request["password_fingerprint"] == "fingerprint"
                assert request["marker"]["first_boot_id"] == "persistent-first"
            return {"boot_id": session["name"], "system": SYSTEM}
        if action == "initialize":
            assert request["new_marker"]["first_boot_id"] == "persistent-first"
            return {"password_fingerprint": "fingerprint"}
        return {"success": True}


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.temp.cleanup()

    def test_explicit_erase_required_before_any_device_action(self):
        calls = []
        installer = SimulatedInstaller(self.directory, calls)
        with self.assertRaisesRegex(RuntimeError, "erase-android-data"):
            installer.run(False)
        self.assertEqual(calls, [])

    def test_pauses_after_reset_then_resumes_without_repartitioning(self):
        calls = []
        installer = SimulatedInstaller(self.directory, calls)
        installer.run(True)
        self.assertNotIn("install", calls)
        self.assertEqual(calls.count("partition"), 1)
        self.assertEqual(calls.count("reboot"), 1)
        self.assertLess(calls.index("backup"), calls.index("partition"))
        self.assertLess(calls.index("partition"), calls.index("reboot"))
        resumed = SimulatedInstaller(self.directory, calls, setup_done=True)
        with patch.object(host, "execute", return_value=subprocess.CompletedProcess([], 0, "$6$testhash\n")):
            resumed.run(False)
        self.assertEqual(calls.count("partition"), 1)
        self.assertEqual(calls.count("install"), 1)
        self.assertEqual(calls.count("initialize"), 1)
        self.assertEqual(calls.count("verify"), 2)
        self.assertLess(calls.index("android-after"), calls.index("install"))
        self.assertLess(calls.index("install"), calls.index("boot:persistent-first"))
        self.assertEqual(resumed.state["steps"]["verify-persistence"]["status"], "complete")
        self.assertEqual((self.directory / "desktop-credentials.txt").stat().st_mode & 0o777, 0o600)
        previous_calls = calls.copy()
        resumed.run(False)
        self.assertEqual(calls, previous_calls)

    def test_ambiguous_partition_result_cannot_be_replayed(self):
        calls = []
        installer = SimulatedInstaller(self.directory, calls, fail="partition")
        with self.assertRaisesRegex(RuntimeError, "lost response"):
            installer.run(True)
        resumed = SimulatedInstaller(self.directory, calls, setup_done=True)
        with self.assertRaisesRegex(RuntimeError, "without a verified result"):
            resumed.run(False)
        self.assertEqual(calls.count("partition"), 1)
        self.assertNotIn("reboot", calls)

    def test_failed_install_never_reformats_or_boots_persistent(self):
        calls = []
        installer = SimulatedInstaller(self.directory, calls, setup_done=True, fail="install")
        with self.assertRaisesRegex(RuntimeError, "lost response"):
            installer.run(True)
        resumed = SimulatedInstaller(self.directory, calls, setup_done=True)
        with self.assertRaisesRegex(RuntimeError, "without a verified result"):
            resumed.run(False)
        self.assertEqual(calls.count("install"), 1)
        self.assertNotIn("boot:persistent-first", calls)

    def test_existing_linux_layout_refused(self):
        calls = []
        installer = SimulatedInstaller(self.directory, calls)
        original_rpc = installer.rpc

        def existing(*args, **kwargs):
            result = original_rpc(*args, **kwargs)
            if args[1] == "inspect":
                result["gpts"][0] = host.writer.prepare(result["gpts"][0], 256)["after"]
            return result
        installer.rpc = existing
        with self.assertRaisesRegex(ValueError, "Linux label already exists"):
            installer.run(True)
        self.assertNotIn("partition", calls)

    def test_source_change_aborts_resume_before_any_device_action(self):
        calls = []
        SimulatedInstaller(self.directory, calls).run(True)
        original_calls = calls.copy()
        with patch.object(host, "source_hashes", return_value={"changed": "yes"}):
            with self.assertRaisesRegex(RuntimeError, "sources changed"):
                SimulatedInstaller(self.directory, calls, setup_done=True)
        self.assertEqual(calls, original_calls)

    def test_archive_metadata_change_blocks_resume(self):
        calls = []
        installer = SimulatedInstaller(self.directory, calls)
        installer.run(True)
        with patch.object(host, "validate_config", return_value=(META | {"archive_bytes": 101}, [SYSTEM])):
            with self.assertRaisesRegex(RuntimeError, "payload changed"):
                host.Installer(installer.config, self.directory)

    def test_gpt_changed_by_stock_reset_blocks_install(self):
        calls = []
        installer = SimulatedInstaller(self.directory, calls)
        installer.run(True)
        resumed = SimulatedInstaller(self.directory, calls, setup_done=True)
        original_rpc = resumed.rpc

        def wrong_gpt(*args, **kwargs):
            result = original_rpc(*args, **kwargs)
            if args[1] == "inspect":
                result["gpts"][1]["regions"]["primary_header"]["sha256"] = "f" * 64
            return result
        resumed.rpc = wrong_gpt
        with self.assertRaisesRegex(RuntimeError, "Post-reset GPT"):
            resumed.run(False)
        self.assertNotIn("install", calls)


class InputGuards(unittest.TestCase):
    def test_failed_or_ambiguous_reboot_is_not_recorded_as_complete(self):
        for events, status in [
            (["reboot-requesting", "stopped"], 1),
            (["reboot-requesting"], 255),
            (["reboot-requesting", "reboot-accepted"], -1),
            (["reboot-accepted", "stopped"], 1),
        ]:
            with self.subTest(events=events, status=status), self.assertRaisesRegex(RuntimeError, "unverified"):
                host.Installer.check_reboot_result(
                    "".join(json.dumps({"event": e}) + "\n" for e in events), status)
        for status in (0, 255):
            host.Installer.check_reboot_result('{"event":"reboot-accepted"}\n', status)

    def test_power_shell_quotes_are_literal(self):
        self.assertEqual(host.ps_quote("x' $(Get-Item .) `test"), "'x'' $(Get-Item .) `test'")
        with self.assertRaisesRegex(RuntimeError, "Newline"):
            host.ps_quote("x\nWrite-Host bad")

    def test_private_state_rejects_public_or_temporary_location(self):
        for path in (PROJECT / "test-private", Path("/tmp/not-durable"), Path("/mnt/c/private")):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                host.private_directory(path)

    def test_private_key_archive_rejects_traversal_links_and_open_modes(self):
        for name, kind, mode in [
            ("../../etc/shadow", tarfile.REGTYPE, 0o600),
            ("etc/ssh/ssh_host_key", tarfile.SYMTYPE, 0o600),
            ("etc/ssh/ssh_host_key", tarfile.REGTYPE, 0o644),
            ("etc/shadow", tarfile.REGTYPE, 0o600),
        ]:
            with self.subTest(name=name, kind=kind, mode=mode), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "keys.tar"
                with tarfile.open(path, "w") as archive:
                    info = tarfile.TarInfo(name)
                    info.type, info.mode = kind, mode
                    archive.addfile(info)
                with self.assertRaises(RuntimeError):
                    device.check_private_tar(path)

    def test_stock_recovery_mismatch_refused(self):
        values = {name: {"bytes": 1048576, "sha256": "0" * 64} for name in device.LABELS}
        with self.assertRaisesRegex(RuntimeError, "Recovery"):
            device.assert_stock(values)

    def test_changes_in_other_lun_are_not_ignored(self):
        expected = six_captures()
        actual = copy.deepcopy(expected)
        actual[-1]["regions"]["pmbr"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "GPT or geometry differs"):
            device.compare_gpts(actual, expected)

    def test_stale_backups_rejected_before_opening_writable_disk(self):
        original = six_captures()
        request = {"boot_id": "maintenance-original",
                   "transaction": host.writer.prepare(original[0], 256),
                   "gpts": original, "backups": {"misc": {"sha256": "old"}}}
        with patch.object(device, "identity"), patch.object(device, "capture", return_value=original), \
                patch.object(device, "check_geometry", return_value={}), \
                patch.object(device, "partition_hashes", return_value={"misc": {"sha256": "new"}}), \
                patch.object(device, "quiesce") as quiesce, patch.object(device.os, "open") as opened:
            with self.assertRaisesRegex(RuntimeError, "Backup no longer matches"):
                device.partition(request)
            quiesce.assert_not_called()
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
