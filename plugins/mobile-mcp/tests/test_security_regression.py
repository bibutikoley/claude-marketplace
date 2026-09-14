"""Attack-oriented regression tests: shell, filesystem, iOS validation, gates.

No real device operations: subprocess/device boundaries are mocked.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import android
import ios
import main


def _shell_env(allow=None, commands=None):
    env = dict(os.environ)
    env.pop("ANDROID_ADB_ALLOW_SHELL", None)
    env.pop("ANDROID_ADB_ALLOWED_COMMANDS", None)
    if allow is not None:
        env["ANDROID_ADB_ALLOW_SHELL"] = allow
    if commands is not None:
        env["ANDROID_ADB_ALLOWED_COMMANDS"] = commands
    return patch.dict(os.environ, env, clear=True)


class TestAndroidShell(unittest.TestCase):
    def test_shell_disabled_by_default(self):
        with _shell_env():
            on, _ = android.shell_allowed()
            self.assertFalse(on)
            with self.assertRaises(android.AndroidError):
                android.run_shell("echo", ["hi"])

    def test_shell_disabled_when_flag_empty(self):
        with _shell_env(allow=""):
            with self.assertRaises(android.AndroidError):
                android.run_shell("echo", ["hi"])

    def test_unapproved_command_rejected(self):
        with _shell_env(allow="1"):
            with self.assertRaises(android.AndroidError):
                android.run_shell("rm", ["-rf", "/"])
            with self.assertRaises(android.AndroidError):
                android.run_shell("echo; rm", ["hi"])
            with self.assertRaises(android.AndroidError):
                android.run_shell("echo|cat", ["hi"])

    def test_approved_command_accepted(self):
        with _shell_env(allow="1"):
            with patch.object(android, "run_device_shell", return_value="ok") as m:
                out = android.run_shell("echo", ["hi"])
                self.assertEqual(out, "ok")
                m.assert_called_once_with(["echo", "hi"], None)

    def test_flag_true_enables(self):
        with _shell_env(allow="true"):
            with patch.object(android, "run_device_shell", return_value="ok"):
                self.assertEqual(android.run_shell("ls", []), "ok")

    def test_custom_allowlist_narrows(self):
        with _shell_env(allow="1", commands="echo,ls"):
            with patch.object(android, "run_device_shell", return_value="ok"):
                self.assertEqual(android.run_shell("echo", ["x"]), "ok")
                with self.assertRaises(android.AndroidError):
                    android.run_shell("cat", ["f"])

    def test_args_with_spaces_preserved_as_argv(self):
        with _shell_env(allow="1"):
            with patch.object(android, "run_device_shell", return_value="ok") as m:
                android.run_shell("echo", ["hello world", "a  b"])
                args = m.call_args[0][0]
                self.assertEqual(args, ["echo", "hello world", "a  b"])

    def test_args_with_quotes_and_metachars_quoted_centrally(self):
        tricky = ["it's", 'say "hi"', "a$b", "x; rm -rf /", "p|q", "r&s", "$(id)"]
        with _shell_env(allow="1"):
            with patch.object(android, "_run_adb", return_value="ok") as m:
                android.run_shell("echo", tricky)
                argv = m.call_args[0][0]
                # One shell word after "shell": values cannot inject commands.
                self.assertEqual(argv[0], "shell")
                self.assertEqual(len(argv), 2)
                import shlex

                self.assertEqual(
                    argv[1], " ".join([shlex.quote("echo")] + [shlex.quote(a) for a in tricky])
                )


class TestAndroidFilesystem(unittest.TestCase):
    def test_protected_root_rejected(self):
        for root in ("/", "/system", "/data", "/dev", "/proc", "/sys"):
            with (
                self.subTest(root=root),
                patch.object(
                    android, "run_device_shell", side_effect=AssertionError("must not run")
                ),
            ):
                with self.assertRaises(android.AndroidError):
                    android.delete_file(root)

    def test_protected_child_rejected(self):
        for child in ("/system/bin/sh", "/data/data/com.foo", "/dev/block/x"):
            with (
                self.subTest(child=child),
                patch.object(
                    android, "run_device_shell", side_effect=AssertionError("must not run")
                ),
            ):
                with self.assertRaises(android.AndroidError):
                    android.delete_file(child)

    def test_path_traversal_rejected(self):
        with patch.object(android, "run_device_shell", side_effect=AssertionError("must not run")):
            with self.assertRaises(android.AndroidError):
                android.delete_file("/sdcard/../system/x")
            with self.assertRaises(android.AndroidError):
                android.delete_file("a/../../etc/passwd")
            with self.assertRaises(android.AndroidError):
                android.delete_file("relative/path.txt")

    def test_unprotected_path_accepted(self):
        with patch.object(android, "run_device_shell", return_value="deleted") as m:
            self.assertEqual(android.delete_file("/sdcard/x.txt"), "deleted")
            m.assert_called_once_with(["rm", "/sdcard/x.txt"], None)

    def test_symlinked_apk_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real.apk"
            real.touch()
            link = Path(tmp) / "link.apk"
            try:
                link.symlink_to(real)
            except OSError:
                self.skipTest("symlinks not supported on this filesystem")
            with patch.dict(os.environ, {"ANDROID_ADB_ALLOWED_INSTALL_DIRS": tmp}):
                with patch.object(
                    android, "_run_android", side_effect=AssertionError("must not run")
                ):
                    with self.assertRaises(android.AndroidError):
                        android.install_apk(str(link), serial="emulator-5554")

    def test_allowed_apk_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp) / "good.apk"
            apk.touch()
            with patch.dict(os.environ, {"ANDROID_ADB_ALLOWED_INSTALL_DIRS": tmp}):
                with patch.object(android, "_run_android", return_value="installed") as m:
                    out = android.install_apk(str(apk), serial="emulator-5554")
                    self.assertEqual(out, "installed")
                    argv = m.call_args[0][0]
                    self.assertIn(f"--apks={apk.resolve()}", argv)

    def test_outside_apk_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "allowed"
            allowed.mkdir()
            outside = Path(tmp) / "evil.apk"
            outside.touch()
            with patch.dict(os.environ, {"ANDROID_ADB_ALLOWED_INSTALL_DIRS": str(allowed)}):
                with patch.object(
                    android, "_run_android", side_effect=AssertionError("must not run")
                ):
                    with self.assertRaises(android.AndroidError):
                        android.install_apk(str(outside), serial="emulator-5554")

    def test_install_options_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp) / "good.apk"
            apk.touch()
            with patch.dict(os.environ, {"ANDROID_ADB_ALLOWED_INSTALL_DIRS": tmp}):
                with patch.object(android, "_run_android", return_value="ok"):
                    android.install_apk(str(apk), serial="s1", install_options="-g,-d")
                    with self.assertRaises(android.AndroidError):
                        android.install_apk(str(apk), serial="s1", install_options="a; rm -rf /")


class TestIOSValidation(unittest.TestCase):
    BAD_IDS = ["bad bundle; id", "../x", "a/b", "", "x$ y", "com.example\n"]

    def test_bundle_id_rejected_simulator(self):
        fns = [
            lambda b: ios.launch_app_simulator(b, None, "U1"),
            lambda b: ios.terminate_app_simulator(b, "U1"),
            lambda b: ios.uninstall_app_simulator(b, "U1"),
            lambda b: ios.get_app_container(b, "data", "U1"),
        ]
        for fn in fns:
            for bad in self.BAD_IDS:
                with self.subTest(bad=bad):
                    with patch.object(
                        ios, "_run_simctl", side_effect=AssertionError("must not run")
                    ):
                        with self.assertRaises(ios.IosError):
                            fn(bad)

    def test_bundle_id_rejected_device(self):
        for fn in [
            lambda b: ios.launch_app_device("D1", b),
            lambda b: ios.terminate_app_device("D1", b),
            lambda b: ios.uninstall_app_device("D1", b),
        ]:
            for bad in self.BAD_IDS:
                with self.subTest(bad=bad):
                    with patch.object(
                        ios, "_run_devicectl", side_effect=AssertionError("must not run")
                    ):
                        with self.assertRaises(ios.IosError):
                            fn(bad)

    def test_valid_bundle_id_accepted(self):
        with (
            patch.object(ios, "resolve_simulator", return_value="U1"),
            patch.object(ios, "_run_simctl", return_value="ok") as m,
        ):
            ios.launch_app_simulator("com.example.app", None, "U1")
            m.assert_called()
        with patch.object(ios, "_run_devicectl", return_value="ok") as m:
            ios.launch_app_device("D1", "com.example.app")
            m.assert_called()

    def test_url_validation(self):
        with (
            patch.object(ios, "resolve_simulator", return_value="U1"),
            patch.object(ios, "_run_simctl", side_effect=AssertionError("must not run")),
        ):
            for bad in [
                "",
                "not a url",
                "://missing-scheme",
                "http://exa mple.com",
                "https://example.com\n",
            ]:
                with self.subTest(url=bad), self.assertRaises(ios.IosError):
                    ios.open_url_simulator(bad)
        with (
            patch.object(ios, "resolve_simulator", return_value="U1"),
            patch.object(ios, "_run_simctl", return_value="") as m,
        ):
            ios.open_url_simulator("myapp://profile/123")
            m.assert_called_with(["openurl", "U1", "myapp://profile/123"], timeout=15.0)

    def test_add_media_missing_file_rejected(self):
        with (
            patch.object(ios, "resolve_simulator", return_value="U1"),
            patch.object(ios, "_run_simctl", side_effect=AssertionError("must not run")),
        ):
            with self.assertRaises(ios.IosError):
                ios.add_media_simulator(["/nonexistent/photo.jpg"], "U1")

    def test_push_payload_must_be_json(self):
        with patch.object(ios, "resolve_simulator", return_value="U1"):
            with self.assertRaises(ios.IosError):
                ios.send_push_notification("com.example.app", "{not-json", "U1")


class TestDestructiveGating(unittest.TestCase):
    """Every destructive tool refuses without confirm and runs with it."""

    def test_all_destructive_tools_gated(self):
        cases = [
            (main.uninstall_app, {"package": "com.example.app"}, "android.uninstall_app"),
            (main.clear_app_data, {"package": "com.example.app"}, "android.clear_app_data"),
            (main.delete_file, {"device_path": "/sdcard/x.txt"}, "android.delete_file"),
            (main.reboot, {}, "android.reboot"),
            (main.ios_erase_simulator, {"udid": "U1"}, "ios.erase_simulator"),
            (
                main.ios_uninstall_app,
                {"bundle_id": "com.example.app", "udid": "U1"},
                "ios.uninstall_app_simulator",
            ),
            (main.ios_device_reboot, {"device_uuid": "D1"}, "ios.reboot_device"),
        ]
        for tool, kwargs, target in cases:
            with self.subTest(tool=tool.__name__):
                module_name, attr = target.split(".")
                module = {"android": android, "ios": ios}[module_name]
                with patch.object(module, attr, return_value="ok") as m:
                    denied = tool(**kwargs)
                    self.assertTrue(denied.is_error, tool.__name__)
                    m.assert_not_called()
                    allowed = tool(**kwargs, confirm=True)
                    self.assertFalse(allowed.is_error, tool.__name__)
                    m.assert_called_once()


if __name__ == "__main__":
    unittest.main()
