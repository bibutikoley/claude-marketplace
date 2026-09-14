"""iOS host install allowlist (IOS_ALLOWED_INSTALL_DIRS).

Policy under test: deny-by-default, os.pathsep-separated roots, ~ expansion,
resolve-before-authorize, nested paths allowed, outside/traversal rejected,
symlinks REJECTED outright (matching Android install_apk).

No real device operations: simctl/devicectl boundaries are mocked.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ios


def _set_allowlist(*dirs: str):
    return patch.dict(os.environ, {"IOS_ALLOWED_INSTALL_DIRS": os.pathsep.join(dirs)})


def _clear_allowlist():
    env = dict(os.environ)
    env.pop("IOS_ALLOWED_INSTALL_DIRS", None)
    return patch.dict(os.environ, env, clear=True)


class TestAllowedInstallDirs(unittest.TestCase):
    def test_empty_allowlist_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "App.app")
            with _clear_allowlist():
                self.assertEqual(ios.allowed_install_dirs(), [])
                with self.assertRaises(ios.IosError):
                    ios.validate_install_path(target)
            with patch.dict(os.environ, {"IOS_ALLOWED_INSTALL_DIRS": ""}):
                self.assertEqual(ios.allowed_install_dirs(), [])
                with self.assertRaises(ios.IosError):
                    ios.validate_install_path(target)

    def test_allowed_path_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "apps"
            allowed.mkdir()
            app = allowed / "MyApp.app"
            app.mkdir()
            with _set_allowlist(str(allowed)):
                resolved = ios.validate_install_path(str(app))
                self.assertEqual(resolved, app.resolve())

    def test_nested_allowed_path_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "builds"
            nested = allowed / "nested" / "deep"
            nested.mkdir(parents=True)
            app = nested / "MyApp.app"
            app.mkdir()
            with _set_allowlist(str(allowed)):
                resolved = ios.validate_install_path(str(app))
                self.assertEqual(resolved, app.resolve())

    def test_outside_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "allowed"
            allowed.mkdir()
            outside = Path(tmp) / "outside" / "Evil.app"
            outside.parent.mkdir(parents=True)
            outside.mkdir()
            with _set_allowlist(str(allowed)):
                with self.assertRaises(ios.IosError):
                    ios.validate_install_path(str(outside))

    def test_relative_path_normalized_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp)
            app = allowed / "RelApp.app"
            app.mkdir()
            old = os.getcwd()
            os.chdir(tmp)
            try:
                with _set_allowlist(tmp):
                    resolved = ios.validate_install_path("RelApp.app")
                    self.assertEqual(resolved, app.resolve())
                    self.assertTrue(resolved.is_absolute())
            finally:
                os.chdir(old)

    def test_tilde_path_normalized_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            apps = home / "apps"
            apps.mkdir()
            app = apps / "Tilde.app"
            app.mkdir()
            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                _set_allowlist("~/apps"),
            ):
                roots = ios.allowed_install_dirs()
                self.assertEqual(roots, [apps.resolve()])
                resolved = ios.validate_install_path("~/apps/Tilde.app")
                self.assertEqual(resolved, app.resolve())

    def test_multiple_allowed_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root1 = Path(tmp) / "one"
            root2 = Path(tmp) / "two"
            root1.mkdir()
            root2.mkdir()
            app1 = root1 / "A.app"
            app2 = root2 / "B.app"
            app1.mkdir()
            app2.mkdir()
            other = Path(tmp) / "other" / "C.app"
            other.parent.mkdir(parents=True)
            other.mkdir()
            with _set_allowlist(str(root1), str(root2)):
                self.assertEqual(len(ios.allowed_install_dirs()), 2)
                self.assertEqual(ios.validate_install_path(str(app1)), app1.resolve())
                self.assertEqual(ios.validate_install_path(str(app2)), app2.resolve())
                with self.assertRaises(ios.IosError):
                    ios.validate_install_path(str(other))

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "allowed"
            allowed.mkdir()
            secret = Path(tmp) / "secret" / "Evil.app"
            secret.parent.mkdir(parents=True)
            secret.mkdir()
            traversal = str(allowed / ".." / "secret" / "Evil.app")
            with _set_allowlist(str(allowed)):
                with self.assertRaises(ios.IosError):
                    ios.validate_install_path(traversal)

    def test_symlink_rejected_even_when_target_inside(self):
        # Explicit policy: symlinks rejected outright (fail-closed),
        # consistent with Android install_apk. Callers pass the real path.
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "allowed"
            allowed.mkdir()
            real = allowed / "Real.app"
            real.mkdir()
            link = allowed / "Link.app"
            try:
                link.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks not supported on this filesystem")
            with _set_allowlist(str(allowed)):
                with self.assertRaises(ios.IosError):
                    ios.validate_install_path(str(link))

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "allowed"
            allowed.mkdir()
            outside = Path(tmp) / "outside-real"
            outside.mkdir()
            link = allowed / "Escape.app"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks not supported on this filesystem")
            with _set_allowlist(str(allowed)):
                with self.assertRaises(ios.IosError):
                    ios.validate_install_path(str(link))

    def test_install_simulator_enforces_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "apps"
            allowed.mkdir()
            app = allowed / "Good.app"
            app.mkdir()
            outside = Path(tmp) / "evil" / "Bad.app"
            outside.parent.mkdir(parents=True)
            outside.mkdir()
            with (
                _set_allowlist(str(allowed)),
                patch.object(ios, "resolve_simulator", return_value="UDID-1"),
                patch.object(ios, "_run_simctl", return_value="") as mock_simctl,
            ):
                msg = ios.install_app_simulator(str(app), "UDID-1")
                self.assertIn("Installed", msg)
                mock_simctl.assert_called_once()
                with self.assertRaises(ios.IosError):
                    ios.install_app_simulator(str(outside), "UDID-1")
                # Outside path never reaches simctl.
                self.assertEqual(mock_simctl.call_count, 1)

    def test_install_device_enforces_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "apps"
            allowed.mkdir()
            ipa = allowed / "Good.ipa"
            ipa.touch()
            outside = Path(tmp) / "evil" / "Bad.ipa"
            outside.parent.mkdir(parents=True)
            outside.touch()
            with (
                _set_allowlist(str(allowed)),
                patch.object(ios, "_run_devicectl", return_value="") as mock_dev,
            ):
                msg = ios.install_app_device("DEV-1", str(ipa))
                self.assertIn("Installed", msg)
                mock_dev.assert_called_once()
                with self.assertRaises(ios.IosError):
                    ios.install_app_device("DEV-1", str(outside))
                self.assertEqual(mock_dev.call_count, 1)

    def test_install_uses_argv_no_shell(self):
        # Authorization must not introduce shell interpolation: the resolved
        # path travels as a single argv element.
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "apps"
            allowed.mkdir()
            tricky = allowed / "My App (1).app"
            tricky.mkdir()
            with (
                _set_allowlist(str(allowed)),
                patch.object(ios, "resolve_simulator", return_value="UDID-1"),
                patch.object(ios, "_run_simctl", return_value="") as mock_simctl,
            ):
                ios.install_app_simulator(str(tricky), "UDID-1")
                argv = mock_simctl.call_args[0][0]
                self.assertIn(str(tricky.resolve()), argv)
                for part in argv:
                    self.assertNotIn(";", part)
                    self.assertNotIn("|", part)


if __name__ == "__main__":
    unittest.main()
