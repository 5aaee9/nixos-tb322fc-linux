import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "nixos/power-key/session-action.sh"


class PowerSessionTests(unittest.TestCase):
    def dispatch(self, action, user="1000", session_class="user",
                 name="y700", locked="no", active="yes",
                 seat="seat0", remote="no", session_type="wayland",
                 account_home=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shim = root / "mock"
            shim.write_text(f"#!{sys.executable}\n" + """
import json,os,sys
from pathlib import Path
cmd=Path(sys.argv[0]).name
args=sys.argv[1:]
if cmd == 'loginctl':
    if args[0] == 'show-seat': print('c1')
    else: print(json.loads(os.environ['SESSION'])[args[args.index('-p')+1]])
elif cmd == 'id':
    print({'gdm':'132','gdm-greeter':'60578','y700':'1000','alice':'1001',
           'root':'0'}[args[-1]])
elif cmd == 'getent':
    user=args[-1]
    uid={'gdm':'132','gdm-greeter':'60578','y700':'1000','alice':'1001','root':'0'}[user]
    home=os.environ['ACCOUNT_HOME'] or ('/run/gdm' if user in ('gdm','gdm-greeter') else '/home/'+user)
    print(f'{user}:x:{uid}:{uid}:GDM:{home}:/bin/false')
elif cmd == 'runuser':
    with open(os.environ['CALLS'],'a') as f: f.write(json.dumps(args)+'\\n')
    if 'org.freedesktop.DBus.Properties.Get' in args: print('(<0>,)')
""")
            shim.chmod(0o755)
            for name_ in ("loginctl", "id", "getent", "runuser"):
                (root / name_).symlink_to(shim)
            script = root / "action.sh"
            script.write_text(SOURCE.read_text())
            calls = root / "calls"
            session = dict(User=user, Class=session_class, Name=name,
                           LockedHint=locked, Active=active, Seat=seat,
                           Remote=remote, Type=session_type)
            env = os.environ | {
                "PATH": str(root) + ":" + os.environ["PATH"],
                "SESSION": json.dumps(session), "ACCOUNT_HOME": account_home or "",
                "CALLS": str(calls),
            }
            result = subprocess.run(["bash", str(script), action], env=env,
                                    capture_output=True, text=True)
            recorded = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            return result, recorded

    def test_desktop_toggle_uses_desktop_bus(self):
        result, calls = self.dispatch("toggle")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Display off", result.stdout)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c[:2] == ["-u", "y700"] for c in calls))
        self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", calls[0])

    def test_greeter_toggle_and_menu_use_only_gdm_bus(self):
        for name, uid in (("gdm", "132"), ("gdm-greeter", "60578")):
            for action in ("toggle", "menu"):
                with self.subTest(name=name, action=action):
                    result, calls = self.dispatch(action, user=uid, session_class="greeter", name=name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(all(c[:2] == ["-u", name] for c in calls))
                    self.assertTrue(all(f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus" in c
                                        for c in calls))
                    if action == "menu":
                        self.assertIn("Shutdown", calls[-1])

    def test_locked_desktop_only_wakes(self):
        result, calls = self.dispatch("menu", locked="yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("Shutdown", calls[0])

    def test_custom_user_and_home(self):
        result, calls = self.dispatch("toggle", user="1001", name="alice",
                                      account_home="/srv/users/alice")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(c[:2] == ["-u", "alice"] for c in calls))
        self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus", calls[0])
        self.assertIn("HOME=/srv/users/alice", calls[0])

    def test_reject_spoofed_greeter_mismatched_user_and_invalid_sessions(self):
        for change in (
            dict(user="1001"),
            dict(user="0", name="root"),
            dict(user="invalid"),
            dict(user="1001", name="gdm", session_class="greeter"),
            dict(user="132", name="gdm-greeter", session_class="greeter"),
            dict(user="132", name="other", session_class="greeter"),
            dict(user="132", name="gdm", session_class="user"),
            dict(active="no"),
            dict(seat="seat1"),
            dict(remote="yes"),
            dict(session_type="tty"),
            dict(session_class="background"),
            dict(account_home="relative-home"),
        ):
            with self.subTest(change=change):
                result, calls = self.dispatch("toggle", **change)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(calls)


if __name__ == "__main__":
    unittest.main()
