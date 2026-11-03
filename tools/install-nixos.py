#!/usr/bin/env python3
"""Staged 256 GiB NixOS installer for unlocked TB322FC, using a Windows + WSL host."""
import argparse
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import uuid

TOOLS = Path(__file__).resolve().parent
PROJECT = TOOLS.parent
ANDROID_BUILD = "TB322FC_CN_OPEN_USER_Q00041.1_W_ZUXOS_1.5.10.229_ST_260514"
POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
SOURCE_FILES = [
    TOOLS / "install-nixos.py", TOOLS / "installer/device.py",
    TOOLS / "storage-layout.py", TOOLS / "prepare-storage-write.py",
    TOOLS / "prepare-recovery-reset.py", TOOLS / "run-usb-nbd-fastboot.ps1",
    TOOLS / "run-usb-debug-fastboot.ps1", TOOLS / "serve-rootfs-nbd.py",
    TOOLS / "usb-gadget-identity.ps1",
]
spec = importlib.util.spec_from_file_location("storage_write", TOOLS / "prepare-storage-write.py")
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def save(path, value, *, replace=False, raw=False):
    path = Path(path)
    payload = value if raw else json_bytes(value)
    require(not path.is_symlink(), "Refusing a symlink destination")
    pending = path.with_name(path.name + ".pending")
    with pending.open("xb") as stream:
        pending.chmod(0o600)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if not replace:
        require(not path.exists(), "Refusing to overwrite " + str(path))
    os.replace(pending, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private_directory(path):
    path = path.expanduser().absolute()
    resolved = path.resolve()
    require(not resolved.is_relative_to(PROJECT), "Installation state/backups must be outside the repository")
    require(not any(resolved.is_relative_to(p) for p in (Path("/tmp"), Path("/run"), Path("/mnt"))),
            "Use durable WSL storage under your home, with Linux file permissions")
    require(path == resolved, "State path may not traverse symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(path.stat().st_mode & 0o777 == 0o700, "State directory must have mode 0700")
    return path


def execute(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, **kwargs)


def ps_quote(value):
    require("\n" not in str(value) and "\r" not in str(value), "Newline in PowerShell argument")
    return "'" + str(value).replace("'", "''") + "'"


def winpath(path):
    return execute(["wslpath", "-w", str(Path(path).absolute())], text=True).stdout.strip()


def example():
    return {
        "schema": 1,
        "serial": "REPLACE_WITH_ADB_SERIAL",
        "android_build": ANDROID_BUILD,
        "slot": "a",
        "linux_gib": 256,
        "adb": "/mnt/c/Users/USERNAME/AppData/Local/Android/Sdk/platform-tools/adb.exe",
        "fastboot": "/mnt/c/Users/USERNAME/AppData/Local/Android/Sdk/platform-tools/fastboot.exe",
        "powershell": POWERSHELL,
        "ssh_private_key": "/home/USERNAME/y700-private/id_ed25519",
        "maintenance_system": "/nix/store/REPLACE_WITH_MAINTENANCE_SYSTEM",
        "maintenance_boot": {"path": "/absolute/path/boot-usb-nbd.img", "sha256": "REPLACE_WITH_SHA256"},
        "maintenance_rootfs": {"path": "/absolute/path/nixos-maintenance.ext4", "sha256": "REPLACE_WITH_SHA256"},
        "persistent_boot": {"path": "/absolute/path/boot.img", "sha256": "REPLACE_WITH_SHA256"},
        "archive": "/absolute/path/nixos-rootfs.tar.gz",
        "archive_metadata": "/absolute/path/metadata.json",
        "archive_closure": "/absolute/path/closure.txt",
    }


def validate_config(config, hash_assets=True):
    require(config["schema"] == 1 and config["linux_gib"] == 256, "Only schema 1 / 256 GiB supported")
    require(config["android_build"] == ANDROID_BUILD, "This Android build's recovery has not been verified")
    require(config["slot"] in ("a", "b"), "Invalid expected slot")
    require(re.fullmatch(r"[A-Za-z0-9._:-]+", config["serial"]) is not None and
            not config["serial"].startswith("REPLACE"), "Set the exact target serial")
    require(re.fullmatch(r"/nix/store/[a-z0-9]{32}-nixos-system-[^/\s]+",
                         config["maintenance_system"]) is not None, "Set the maintenance system store path")
    for name in ("adb", "fastboot", "powershell", "ssh_private_key"):
        require(Path(config[name]).is_file(), "Missing " + name + " file")
    require(Path(config["ssh_private_key"]).stat().st_mode & 0o077 == 0, "SSH private key permissions")
    meta = json.loads(Path(config["archive_metadata"]).read_text())
    closure = Path(config["archive_closure"]).read_text().splitlines()
    require(re.fullmatch(r"/nix/store/[a-z0-9]{32}-nixos-system-[^/\s]+", meta["system"]) is not None,
            "Invalid archive system")
    require(meta["system"] in closure and len(closure) == len(set(closure)) == meta["closure_paths"],
            "Archive closure count/system")
    require(all(re.fullmatch(r"/nix/store/[a-z0-9]{32}-[^/\s]+", p) for p in closure),
            "Invalid closure path")
    expected_kernel = json.loads((PROJECT / "vendor/tb322fc-linux/sources.json").read_text())["kernel"]
    expected_nixpkgs = json.loads((PROJECT / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"]
    require(meta["kernel"] == expected_kernel and meta["nixpkgs"] == expected_nixpkgs,
            "Archive source pins differ from this checkout")
    for name in ("maintenance_boot", "maintenance_rootfs", "persistent_boot"):
        item = config[name]
        require(Path(item["path"]).is_file() and re.fullmatch("[0-9a-f]{64}", item["sha256"]),
                "Missing artifact or invalid checksum: " + name)
        if hash_assets:
            print("Checking " + name + "...", flush=True)
            require(digest(item["path"]) == item["sha256"], name + " checksum mismatch")
    archive = Path(config["archive"])
    require(archive.is_file() and archive.stat().st_size == meta["archive_bytes"], "Archive size")
    if hash_assets:
        print("Checking installation archive...", flush=True)
        require(digest(archive) == meta["archive_sha256"], "Archive checksum mismatch")
    return meta, closure


def source_hashes():
    return {str(p.relative_to(PROJECT)): digest(p) for p in SOURCE_FILES}


class Installer:
    def __init__(self, config, directory):
        self.config = config
        self.directory = directory
        self.path = directory / "state.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            "schema": 1, "config": config, "source_sha256": source_hashes(), "steps": {},
            "id": uuid.uuid4().hex, "erase_android_authorized": False,
        }
        require(self.state["config"] == config, "Configuration changed; inspect the existing session")
        require(self.state["source_sha256"] == source_hashes(), "Installer sources changed mid-session")
        self.meta, self.closure = validate_config(config, hash_assets=False)
        payload = {"metadata": self.meta, "closure": self.closure}
        if self.path.exists():
            require(self.state["payload"] == payload, "Installation payload changed mid-session")
        else:
            self.state["payload"] = payload

    def persist(self):
        save(self.path, self.state, replace=self.path.exists())

    def step(self, name, function):
        old = self.state["steps"].get(name)
        if old:
            require(old["status"] == "complete",
                    f"{name} was started without a verified result. Do not retry writes; inspect private logs.")
            return old["result"]
        print("Step: " + name, flush=True)
        self.state["steps"][name] = {"status": "started", "host_time": time.time()}
        self.persist()
        value = function()
        self.state["steps"][name] = {"status": "complete", "host_time": time.time(), "result": value}
        self.persist()
        return value

    def adb(self, command):
        return execute([self.config["adb"], "-s", self.config["serial"], "shell", command],
                       text=True, timeout=15).stdout.strip()

    def android(self, after=False, wait=False):
        if wait:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                try:
                    if self.adb("getprop sys.boot_completed") == "1":
                        break
                except (subprocess.SubprocessError, OSError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("Android did not become available; do not repeat reboot")
        properties = ["ro.product.model", "ro.build.display.id", "ro.serialno", "ro.boot.slot_suffix",
                      "ro.boot.flash.locked", "ro.boot.vbmeta.device_state", "sys.boot_completed"]
        values = dict(zip(properties, self.adb("; ".join("getprop " + p for p in properties)).splitlines()))
        expected = ["TB322FC", self.config["android_build"], self.config["serial"],
                    "_" + self.config["slot"], "0", "unlocked", "1"]
        require(values == dict(zip(properties, expected)), "Android identity/build/slot/unlock mismatch")
        battery = re.search(r"level:\s*(\d+)", self.adb("dumpsys battery"))
        require(battery and int(battery.group(1)) >= 50, "Battery must be at least 50 percent")
        result = {"properties": values, "battery": int(battery.group(1))}
        if after:
            capacity = int(self.adb("df -k /data").splitlines()[-1].split()[1]) * 1024
            expected_bytes = self.state["transaction"]["proposal"]["userdata"]["proposed_bytes"]
            require(expected_bytes * .95 < capacity <= expected_bytes, "Android data was not recreated at the new size")
            data = [l.split() for l in self.adb("cat /proc/mounts").splitlines() if l.split()[1] == "/data"]
            require(len(data) == 1 and data[0][2] == "f2fs" and "rw" in data[0][3].split(","),
                    "Android /data is not writable F2FS")
            require(self.adb("settings get global device_provisioned") == "1" and
                    self.adb("settings get secure user_setup_complete") == "1", "Finish Android initial setup")
            result["data_filesystem_bytes"] = capacity
        return result

    def fastboot(self, variable):
        p = execute([self.config["fastboot"], "-s", self.config["serial"], "getvar", variable],
                    text=True, timeout=12)
        text = p.stdout + p.stderr
        require("FAILED" not in text, "fastboot query failed")
        match = re.search(r"(?m)^(?:\(bootloader\)\s*)?" + re.escape(variable) + r":\s*(.*?)\s*$", text)
        require(match is not None, "Missing fastboot variable " + variable)
        return match.group(1)

    def host_cleanup(self, previous):
        folder = Path(previous["host_directory"])
        deadline = time.monotonic() + 360
        while not (folder.parent / "host-complete.json").exists():
            require(time.monotonic() < deadline, "Previous host helper is still active; preserve it and inspect")
            time.sleep(1)
        ready = json.loads((folder / "ready.json").read_text(encoding="utf-8-sig"))
        guid = ready["interface_guid"]
        require(re.fullmatch(r"[{]?[0-9a-fA-F-]{36}[}]?", guid), "Invalid recorded interface GUID")
        # Detached Windows gadgets cannot always be enumerated. Audit the saved
        # GUID's DHCP registry state and all remaining addresses without mutations.
        script = (
            "$ErrorActionPreference='Stop'\n"
            "if(Get-NetIPAddress -AddressFamily IPv4 -PolicyStore ActiveStore | "
            "Where-Object {$_.IPAddress -eq '192.168.42.1'}) {throw 'Temporary IP remains'}\n"
            "if(Get-NetTCPConnection -State Listen -LocalPort 10809 -ErrorAction SilentlyContinue) "
            "{throw 'NBD listener remains'}\n"
            "$key='HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\{" +
            guid.strip("{}") + "}'\n"
            f"if((Get-ItemProperty -LiteralPath $key).EnableDHCP -ne "
            f"{1 if ready['original_dhcp'] == 'Enabled' else 0}) {{throw 'DHCP state differs'}}\n"
        )
        if ready.get("firewall_rule"):
            script += ("if(Get-NetFirewallRule -DisplayName " + ps_quote(ready["firewall_rule"]) +
                       " -ErrorAction SilentlyContinue) {throw 'Test firewall rule remains'}\n")
        path = folder.parent / "cleanup-audit.ps1"
        save(path, script.encode(), raw=True)
        execute([self.config["powershell"], "-NoProfile", "-NonInteractive", "-File", winpath(path)],
                text=True, timeout=20)
        save(folder.parent / "cleanup-audit.json", {"passed": True, "host_time": time.time()})

    def boot(self, name, persistent=False, previous=None):
        if previous:
            self.host_cleanup(previous)
        self.android(after="transaction" in self.state)
        execute([self.config["adb"], "-s", self.config["serial"], "reboot", "bootloader"],
                text=True, timeout=20)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            p = execute([self.config["fastboot"], "-s", self.config["serial"], "devices"],
                        text=True, timeout=5)
            if any(line.split()[0] == self.config["serial"] for line in p.stdout.splitlines() if line.split()):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Target did not reach bootloader; reboot is not retried")
        for variable, expected in [("product", "elden_prc_wifi"), ("hwboardid", "TB322FC_SM8750P_16+512"),
                                   ("unlocked", "yes"), ("current-slot", self.config["slot"]),
                                   ("is-userspace", "no")]:
            require(self.fastboot(variable) == expected, "Fastboot target mismatch: " + variable)
        if "transaction" in self.state:
            proposal = self.state["transaction"]["proposal"]
            sizes = {"userdata": proposal["userdata"]["proposed_bytes"],
                     **{p["label"]: p["bytes"] for p in proposal["new_partitions"]}}
            for label, size in sizes.items():
                require(int(self.fastboot("partition-size:" + label), 16) == size, "Fastboot partition size")
        folder = self.directory / name
        folder.mkdir(mode=0o700)
        boot_key = "persistent_boot" if persistent else "maintenance_boot"
        boot = self.config[boot_key]
        require(digest(boot["path"]) == boot["sha256"], "Boot image changed since plan")
        helper = TOOLS / ("run-usb-debug-fastboot.ps1" if persistent else "run-usb-nbd-fastboot.ps1")
        arguments = {
            "BootImage": winpath(boot["path"]), "FastbootPath": winpath(self.config["fastboot"]),
            "FastbootSerial": self.config["serial"], "ExpectedSlot": self.config["slot"],
            "LogDirectory": winpath(folder / "host"),
        }
        if persistent:
            arguments["ExpectedBootSHA256"] = boot["sha256"]
        else:
            rootfs = self.config["maintenance_rootfs"]
            require(digest(rootfs["path"]) == rootfs["sha256"], "Maintenance rootfs changed")
            arguments["RootfsImage"] = winpath(rootfs["path"])
        runner = "$ErrorActionPreference='Stop'\n$code=0\ntry {\n& " + ps_quote(winpath(helper))
        runner += "".join(" -" + k + " " + ps_quote(v) for k, v in arguments.items())
        runner += ("\n} catch {$code=1; $_ | Out-String | Set-Content -LiteralPath " +
                   ps_quote(winpath(folder / "host-error.txt")) + "}\nfinally {\n"
                   "@{exit_code=$code;finished=(Get-Date).ToString('o')} | ConvertTo-Json | "
                   "Set-Content -LiteralPath " + ps_quote(winpath(folder / "host-complete.json")) + "\n}\n")
        save(folder / "run.ps1", runner.encode(), raw=True)
        launch = ("$ErrorActionPreference='Stop'\n$p=" + ps_quote(winpath(folder / "run.ps1")) +
                  "\n$a='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"'+$p+'\"'\n"
                  "Start-Process -FilePath \"$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe\" "
                  "-Verb RunAs -ArgumentList $a -PassThru | Select-Object Id | ConvertTo-Json\n")
        save(folder / "launch.ps1", launch.encode(), raw=True)
        launched = execute([self.config["powershell"], "-NoProfile", "-NonInteractive",
                            "-File", winpath(folder / "launch.ps1")], text=True, timeout=60)
        save(folder / "host-launch.txt", launched.stdout.encode(), raw=True)
        deadline = time.monotonic() + 180
        while not (folder / "host/ready.json").exists():
            require(not (folder / "host-complete.json").exists(), "USB helper stopped; inspect private host logs")
            require(time.monotonic() < deadline, "USB helper not ready; inspect, do not boot again")
            time.sleep(1)
        ready = json.loads((folder / "host/ready.json").read_text(encoding="utf-8-sig"))
        require(ready.get("usb_port_verified") is True, "USB helper has not verified the target physical port")
        known = folder / "known_hosts"
        if persistent:
            require(previous is not None, "Missing maintenance host identity")
            shutil.copyfile(previous["known_hosts"], known)
            known.chmod(0o600)
        ssh = ["ssh", "-4", "-F", "/dev/null", "-i", self.config["ssh_private_key"],
               "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
               "-o", "UserKnownHostsFile=" + str(known), "-o",
               "StrictHostKeyChecking=" + ("yes" if persistent else "accept-new"), "root@192.168.42.2"]
        # Initial trust is limited to the new, serial-booted direct USB gadget.
        # Subsequent connections, including persistent boots, require the saved key.
        deadline = time.monotonic() + 150
        discovery = ("for p in /nix/store/*-python3-*/bin/python3; do "
                     "if \"$p\" -c 'import sys; sys.exit(sys.version_info < (3,11))' 2>/dev/null; "
                     "then printf '%s\\n' \"$p\"; break; fi; done")
        while time.monotonic() < deadline:
            p = subprocess.run(ssh + [discovery], capture_output=True, text=True, timeout=10)
            if p.returncode == 0 and p.stdout.strip():
                python = p.stdout.strip()
                break
            time.sleep(2)
        else:
            raise RuntimeError("Trusted USB SSH/interpreter unavailable; preserve host helper")
        require(re.fullmatch(r"/nix/store/[a-z0-9]{32}-python3-[^/\s]+/bin/python3", python),
                "Unexpected device Python path")
        known.chmod(0o600)
        ssh[ssh.index("StrictHostKeyChecking=" + ("yes" if persistent else "accept-new"))] = "StrictHostKeyChecking=yes"
        return {"ssh": ssh, "python": python, "known_hosts": str(known),
                "host_directory": str(folder / "host")}

    def upload(self, session, remote, local):
        local = Path(local)
        with local.open("rb") as source:
            code = "import sys; from pathlib import Path; p=Path(sys.argv[1]); p.open('xb').close(); p.chmod(0o600)"
            execute(session["ssh"] + [shlex.join([session["python"], "-c", code, remote])], timeout=15)
            offset = 0
            while block := source.read(64 * 1024 ** 2):
                sha = hashlib.sha256(block).hexdigest()
                code = ("import sys,hashlib; from pathlib import Path; p=Path(sys.argv[1]); "
                        "b=sys.stdin.buffer.read(); "
                        f"assert p.stat().st_size=={offset} and len(b)=={len(block)}; "
                        f"assert hashlib.sha256(b).hexdigest()=={sha!r}; "
                        "f=p.open('ab'); assert f.write(b)==len(b); f.close()")
                execute(session["ssh"] + [shlex.join([session["python"], "-c", code, remote])],
                        input=block, timeout=180)
                offset += len(block)
                print(f"  Transferred {local.name}: {offset}/{local.stat().st_size}", flush=True)

    def rpc(self, session, action, request, files=None, reboot=False):
        remote = "/run/y700-installer-" + uuid.uuid4().hex
        local = self.directory / ("rpc-" + action + "-" + uuid.uuid4().hex[:8])
        local.mkdir(mode=0o700)
        code = ("from pathlib import Path; import os,sys; p=Path(sys.argv[1]); "
                "p.mkdir(mode=0o700); v=os.statvfs('/run'); "
                f"assert v.f_bavail*v.f_frsize > {self.meta['archive_bytes'] + 512*1024**2 if action == 'install' else 256*1024**2}")
        execute(session["ssh"] + [shlex.join([session["python"], "-c", code, remote])], timeout=15)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            entries = {p.name: p.read_bytes() for p in SOURCE_FILES[:5] if p.name != "install-nixos.py"}
            entries["request.json"] = json_bytes(request)
            for name, content in entries.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(content), 0o600
                archive.addfile(info, io.BytesIO(content))
        execute(session["ssh"] + [shlex.join(["tar", "--keep-old-files", "-xf", "-", "-C", remote])],
                input=buffer.getvalue(), timeout=30)
        for name, path in (files or {}).items():
            self.upload(session, remote + "/" + name, path)
        log = local / "stdout.jsonl"
        command = shlex.join([session["python"], remote + "/device.py", action, remote + "/request.json"])
        with log.open("xb") as stdout, (local / "stderr.txt").open("xb") as stderr:
            try:
                p = subprocess.run(session["ssh"] + [command], stdout=stdout, stderr=stderr,
                                   timeout=30 if reboot else 3600)
                status = p.returncode
            except subprocess.TimeoutExpired:
                status = -1
        save(local / "invocation.json", {"action": action, "remote": remote, "exit_code": status})
        if reboot:
            self.check_reboot_result(log.read_text(), status)
            return {"requested": True, "exit_code": status}
        if status:
            raise RuntimeError(f"Device {action} stopped; logs: {local}. Keep the maintenance/NBD session running.")
        result = json.loads(execute(session["ssh"] + ["cat " + shlex.quote(remote + "/" + action + "-result.json")],
                                   text=True, timeout=15).stdout)
        if action == "keys":
            target = self.directory / "ssh-host-state.tar"
            self.download(session, remote + "/ssh-host-state.tar", target, result)
        save(local / "result.json", result)
        # Only request.json may hold the one-time password hash; it remains in
        # private RAM. Leave failed operations intact for manual diagnosis.
        return result

    @staticmethod
    def check_reboot_result(log, status):
        events = [json.loads(line).get("event") for line in log.splitlines() if line.startswith("{")]
        require("stopped" not in events and status in (0, 255) and "reboot-accepted" in events,
                "Reboot acceptance is unverified; inspect state before any retry")

    def download(self, session, remote, path, expected):
        pending = Path(str(path) + ".transfer")
        with pending.open("xb") as stream:
            os.chmod(pending, 0o600)
            p = subprocess.run(session["ssh"] + ["cat " + shlex.quote(remote)], stdout=stream,
                               stderr=subprocess.PIPE, timeout=300)
            require(p.returncode == 0, "Backup transfer failed")
            stream.flush()
            os.fsync(stream.fileno())
        require(pending.stat().st_size == expected["bytes"] and digest(pending) == expected["sha256"],
                "Backup transfer hash/size mismatch")
        after = execute(session["ssh"] + [shlex.join(["sha256sum", remote])], text=True, timeout=180).stdout.split()[0]
        require(after == expected["sha256"], "Source changed during backup")
        require(not path.exists(), "Backup destination already exists")
        os.replace(pending, path)

    def backups(self, session, inspection):
        required = sum(v["bytes"] for v in inspection["backups"].values())
        require(shutil.disk_usage(self.directory).free > required + 512 * 1024 ** 2, "Insufficient backup space")
        for label, value in inspection["backups"].items():
            print("  Backing up " + label, flush=True)
            self.download(session, "/dev/disk/by-partlabel/" + label, self.directory / (label + ".img"), value)
        save(self.directory / "all-gpt.json", inspection["gpts"])
        save(self.directory / "backup-manifest.json", inspection["backups"])
        return {"verified": True}

    def request(self, inspection, persistent=False):
        return {"system": self.meta["system"] if persistent else self.config["maintenance_system"],
                "boot_id": inspection["boot_id"], "transaction": self.state["transaction"],
                "gpts": self.state["steps"]["inspect-original"]["result"]["gpts"],
                "backups": self.state["steps"]["inspect-original"]["result"]["backups"]}

    def run(self, erase):
        if not self.state["erase_android_authorized"]:
            require(erase, "First run requires --erase-android-data; plan never changes the tablet")
            self.state["erase_android_authorized"] = True
            self.persist()
        self.step("android-original", self.android)
        first = self.step("maintenance-original", lambda: self.boot("maintenance-original"))
        original = self.step("inspect-original", lambda: self.rpc(first, "inspect",
            {"system": self.config["maintenance_system"], "fresh": True}))
        self.step("backup-original", lambda: self.backups(first, original))
        if "transaction" not in self.state:
            matches = [c for c in original["gpts"] if any(p["label"] == "userdata"
                       for p in writer.layout.decode_capture(c, allow_vendor_reservations=True)[1])]
            require(len(matches) == 1 and matches[0]["disk_bytes"] == 507376566272, "Unexpected 512 GB data LUN")
            transaction = writer.prepare(matches[0], 256)
            save(self.directory / "gpt-transaction.json", transaction)
            self.state["transaction"] = transaction
            self.persist()
        self.step("partition", lambda: self.rpc(first, "partition", self.request(original),
                  {"misc.img": self.directory / "misc.img"}))
        self.step("reset-reboot", lambda: self.rpc(first, "reboot",
                  self.request(original) | {"reset_armed": True},
                  {"misc.img": self.directory / "misc.img"}, reboot=True))
        if "android-recreated" not in self.state["steps"]:
            try:
                android = self.android(after=True)
            except (RuntimeError, subprocess.SubprocessError, OSError, ValueError):
                print("Stock Android reset requested. Finish Android setup, enable USB debugging,\n"
                      "authorize this host, then run the same command again. The reset is not repeated.", flush=True)
                return
            self.step("android-recreated", lambda: android)
        second = self.step("maintenance-after-reset", lambda: self.boot("maintenance-after-reset", previous=first))
        inspected = self.step("inspect-after-reset", lambda: self.rpc(second, "inspect",
                              {"system": self.config["maintenance_system"], "fresh": False}))
        expected = [self.state["transaction"]["after"] if c["controller_lun"] ==
                    self.state["transaction"]["before"]["controller_lun"] else c for c in original["gpts"]]
        require({c["controller_lun"]: c["regions"] for c in inspected["gpts"]} ==
                {c["controller_lun"]: c["regions"] for c in expected}, "Post-reset GPT differs from plan")
        keys = self.step("save-host-identity", lambda: self.rpc(second, "keys", self.request(inspected)))
        self.step("install-rootfs", lambda: self.rpc(second, "install",
                  self.request(inspected) | {"archive": self.meta, "closure": self.closure,
                                           "host_keys_sha256": keys["sha256"]},
                  {"nixos-rootfs.tar.gz": self.config["archive"],
                   "ssh-host-state.tar": self.directory / "ssh-host-state.tar"}))
        self.step("maintenance-return-android", lambda: self.rpc(second, "reboot",
                  self.request(inspected), reboot=True))
        self.step("android-after-install", lambda: self.android(after=True, wait=True))
        linux1 = self.step("persistent-first", lambda: self.boot("persistent-first", persistent=True, previous=second))
        verify_request = self.request(inspected, persistent=True)
        verify_request.pop("boot_id")
        verified = self.step("verify-first", lambda: self.rpc(linux1, "verify", verify_request))
        if "credentials" not in self.state:
            password = secrets.token_urlsafe(18)
            secret_hash = execute(["openssl", "passwd", "-6", "-stdin"],
                                  input=password + "\n", text=True).stdout.strip()
            save(self.directory / "desktop-credentials.txt",
                 ("NixOS user: y700\nPassword: " + password + "\nChange after signing in.\n").encode(), raw=True)
            self.state["credentials"] = {"password_hash": secret_hash, "marker": {
                "nonce": secrets.token_hex(32), "first_boot_id": verified["boot_id"]}}
            self.persist()
        credentials = self.state["credentials"]
        initialized = self.step("initialize-desktop", lambda: self.rpc(linux1, "initialize",
                  verify_request | {"boot_id": verified["boot_id"], "password_hash": credentials["password_hash"],
                                    "new_marker": credentials["marker"]}))
        self.step("persistent-return-android", lambda: self.rpc(linux1, "reboot",
                  verify_request | {"boot_id": verified["boot_id"], "persistent": True}, reboot=True))
        self.step("android-roundtrip", lambda: self.android(after=True, wait=True))
        linux2 = self.step("persistent-second", lambda: self.boot("persistent-second", persistent=True, previous=linux1))
        self.step("verify-persistence", lambda: self.rpc(linux2, "verify",
                  verify_request | {"marker": credentials["marker"],
                                    "password_fingerprint": initialized["password_fingerprint"]}))
        print("Installation verified: two internal-root boots and Android return.\n"
              "Desktop user: y700. Password file: " + str(self.directory / "desktop-credentials.txt") +
              "\nReconnect Wi-Fi. Android remains the default boot path; Linux still uses fastboot boot.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["example", "plan", "run", "status"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--erase-android-data", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "example":
        require(args.output is not None, "example requires --output")
        save(args.output, example())
        print("Private configuration template: " + str(args.output))
        return
    require(args.config is not None, "--config is required")
    config = json.loads(args.config.read_text())
    if args.action == "plan":
        meta, _ = validate_config(config)
        plan = {"device": "TB322FC/elden 512 GB", "linux_gib": 256, "esp_gib": 1,
                "rootfs_gib": 255, "erase_android_userdata": True,
                "preserve_installed_boot_images": True, "openabl_installed": False,
                "system": meta["system"], "source_sha256": source_hashes(),
                "steps": ["ADB identity and battery", "RAM maintenance fastboot boot",
                          "six GPTs and own boot-chain/metadata/misc backups",
                          "verified stock reset request then backup-first GPT",
                          "stock Android reset/setup/USB authorization",
                          "fresh maintenance boot and exact GPT revalidation",
                          "format new ESP/rootfs, extract/register/check, publish contract last",
                          "local-root boot, private password, Android round trip, persistence check"]}
        if args.output:
            save(args.output, plan)
        print(json.dumps(plan, indent=2))
        return
    require(args.state_dir is not None, "--state-dir is required")
    directory = private_directory(args.state_dir)
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        installer = Installer(config, directory)
        if args.action == "status":
            for name, step in installer.state["steps"].items():
                print(name + ": " + step["status"])
            return
        require("microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower(), "Run from WSL on Windows")
        for name in ("ssh", "openssl", "wslpath"):
            require(shutil.which(name), "Missing host tool: " + name)
        validate_config(config)
        installer.run(args.erase_android_data)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("Stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
