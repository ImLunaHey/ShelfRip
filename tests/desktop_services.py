"""Optional native integration suite: python3 tests/desktop_services.py.

Needs dbus-run-session, Xvfb/xauth, GTK3, Ayatana AppIndicator3, secret-tool,
gnome-keyring and PyGObject (test harness only). Creates a private D-Bus session
and temporary home; never reads or modifies the login session's keyring.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def isolated_session():
    with tempfile.TemporaryDirectory(prefix="shelfrip-desktop-") as tmp:
        env = {**os.environ, "HOME": tmp, "XDG_CONFIG_HOME": tmp + "/config",
               "XDG_DATA_HOME": tmp + "/data", "XDG_CACHE_HOME": tmp + "/cache",
               "XDG_RUNTIME_DIR": tmp + "/run", "SHELFRIP_DATA": tmp + "/shelfrip",
               "PYTHONDONTWRITEBYTECODE": "1", "GTK_MODULES": "", "NO_AT_BRIDGE": "1"}
        for key in ("DBUS_SESSION_BUS_ADDRESS", "GNOME_KEYRING_CONTROL", "WAYLAND_DISPLAY"):
            env.pop(key, None)
        Path(env["XDG_RUNTIME_DIR"]).mkdir(mode=0o700)
        return subprocess.run(["dbus-run-session", "--", "xvfb-run", "-a", sys.executable,
                               str(Path(__file__).resolve()), "--session"], env=env).returncode


if __name__ == "__main__" and "--session" not in sys.argv:
    raise SystemExit(isolated_session())

if "--session" in sys.argv:
    sys.argv.remove("--session")
    from gi.repository import Gio, GLib
    import desktop
    import linux_keyring
    import linux_tray
    import app
    import paths

    WATCHER = "org.kde.StatusNotifierWatcher"
    XML = '''<node><interface name="org.kde.StatusNotifierWatcher">
      <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
      <method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
      <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
      <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
      <property name="ProtocolVersion" type="i" access="read"/>
      <signal name="StatusNotifierHostRegistered"/>
      <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
    </interface></node>'''

    def eventually(predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.05)
        raise AssertionError("Desktop service did not reach expected state")

    class Services(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            subprocess.run(["gnome-keyring-daemon", "--unlock", "--components=secrets"],
                           input=b"isolated-test-keyring", check=True, capture_output=True, timeout=10)
            cls.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            cls.loop = GLib.MainLoop()
            cls.thread = threading.Thread(target=cls.loop.run, daemon=True)
            cls.thread.start()

        @classmethod
        def tearDownClass(cls):
            cls.loop.quit()
            cls.thread.join(timeout=3)

        def test_real_keyring_migration_replacement_and_removal(self):
            password = " test-only ü\n"
            paths.write_config({"opensubtitles_password": password})
            app.migrate_password()
            first = json.loads(paths.CONFIG_PATH.read_text())["opensubtitles_password"]
            self.assertTrue(linux_keyring.is_reference(first))
            self.assertEqual(linux_keyring.lookup(first), password)
            self.assertNotIn(password, paths.CONFIG_PATH.read_text())
            try:
                app._save_settings({"opensubtitles_password": "replacement test-only"})
                second = json.loads(paths.CONFIG_PATH.read_text())["opensubtitles_password"]
                self.assertNotEqual(first, second)
                self.assertEqual(linux_keyring.lookup(second), "replacement test-only")
                with self.assertRaises(linux_keyring.KeyringError):
                    linux_keyring.lookup(first)
                app._save_settings({"opensubtitles_password": None})
                with self.assertRaises(linux_keyring.KeyringError):
                    linux_keyring.lookup(second)
            finally:
                linux_keyring.cleanup(first)
                linux_keyring.cleanup(json.loads(paths.CONFIG_PATH.read_text()).get("opensubtitles_password", ""))

        def test_real_indicator_menu_reconnection_and_cleanup(self):
            registered = []

            def method(conn, sender, path, interface, name, parameters, invocation):
                value = parameters.unpack()[0]
                if name == "RegisterStatusNotifierItem":
                    registered.append((sender, value) if value.startswith("/") else (value, "/StatusNotifierItem"))
                invocation.return_value(None)

            def prop(*args):
                name = args[-1]
                return {"IsStatusNotifierHostRegistered": GLib.Variant("b", True),
                        "RegisteredStatusNotifierItems": GLib.Variant("as", []),
                        "ProtocolVersion": GLib.Variant("i", 0)}[name]

            object_id = self.bus.register_object("/StatusNotifierWatcher",
                Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], method, prop, None)
            acquired = threading.Event()
            def own():
                acquired.clear()
                owner = Gio.bus_own_name_on_connection(self.bus, WATCHER, Gio.BusNameOwnerFlags.NONE,
                    lambda *_: acquired.set(), None)
                self.assertTrue(acquired.wait(5))
                return owner
            owner = own()
            clicked = threading.Event()
            tray = desktop.create_tray("Shelfrip test", None,
                lambda: [("Open Shelfrip", clicked.set), ("Status", None), None, ("Quit", clicked.set)])
            try:
                self.assertTrue(tray.start(), tray.error)
                eventually(lambda: registered)
                destination, path = registered[-1]
                def call(interface, name, signature, args, target=path):
                    return self.bus.call_sync(destination, target, interface, name,
                        GLib.Variant(signature, args), None, Gio.DBusCallFlags.NONE, 5000, None).unpack()
                menu_path = call("org.freedesktop.DBus.Properties", "Get", "(ss)",
                    ("org.kde.StatusNotifierItem", "Menu"))[0]
                def layout():
                    return call("com.canonical.dbusmenu", "GetLayout", "(iias)", (0, -1, []), menu_path)[1]
                eventually(lambda: len(layout()[2]) == 4)
                items = layout()[2]
                self.assertEqual(items[0][1]["label"], "Open Shelfrip")
                self.assertFalse(items[1][1]["enabled"])
                self.assertEqual(items[2][1]["type"], "separator")
                call("com.canonical.dbusmenu", "Event", "(isvu)",
                     (items[0][0], "clicked", GLib.Variant("i", 0), 0), menu_path)
                self.assertTrue(clicked.wait(5), "Native menu activation did not reach Python callback")
                for n in range(10):
                    tray.set_tip(f"Updated {n}")
                eventually(lambda: call("org.freedesktop.DBus.Properties", "Get", "(ss)",
                    ("org.kde.StatusNotifierItem", "Title"))[0] == "Updated 9")
                Gio.bus_unown_name(owner)
                owner = None
                eventually(lambda: not tray.ok)
                owner = own()
                eventually(lambda: tray.ok)
                # Abrupt app death must also close the helper's input and remove its icon.
                parent = subprocess.Popen([sys.executable, "-c",
                    "import desktop,time; t=desktop.create_tray('Crash test',None,lambda: [('Open',lambda:None)]); "
                    "assert t.start(),t.error; print(t.proc.pid,flush=True); time.sleep(60)"],
                    cwd=ROOT, stdout=subprocess.PIPE, text=True)
                try:
                    import select
                    self.assertTrue(select.select([parent.stdout], [], [], 12)[0])
                    helper_pid = int(parent.stdout.readline())
                    parent.kill()
                    parent.wait(timeout=3)
                    def helper_stopped():
                        stat = Path(f"/proc/{helper_pid}/stat")
                        return not stat.exists() or stat.read_text().split(")", 1)[1].split()[0] == "Z"
                    eventually(helper_stopped)
                finally:
                    if parent.poll() is None:
                        parent.kill()
                    parent.wait(timeout=3)
                    parent.stdout.close()
            finally:
                tray.remove()
                if owner is not None:
                    Gio.bus_unown_name(owner)
                self.bus.unregister_object(object_id)
            self.assertEqual(tray.proc.returncode, 0)
            self.assertFalse(tray.ok)

        def test_missing_host_exits_helper_and_keeps_app_usable(self):
            tray = desktop.create_tray("Shelfrip test", None, lambda: [("Open", lambda: None)])
            try:
                self.assertFalse(tray.start())
                self.assertIn("tray host", tray.error)
                self.assertIsNotNone(tray.proc.poll())
            finally:
                tray.remove()

    unittest.main()
