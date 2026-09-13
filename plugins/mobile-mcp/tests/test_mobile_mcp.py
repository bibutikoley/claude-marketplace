import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure mobile-mcp plugin directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import android
import ios
import main


class TestMobileMcp(unittest.TestCase):
    def test_key_event_formatting(self):
        with patch.object(android, "run_device_shell") as mock_shell:
            # Numeric code 4 should remain "4"
            android.key_event("4")
            mock_shell.assert_called_with(["input", "keyevent", "4"], None)

            # Numeric code 66 should remain "66"
            android.key_event("66")
            mock_shell.assert_called_with(["input", "keyevent", "66"], None)

            # Named code BACK should become KEYCODE_BACK
            android.key_event("back")
            mock_shell.assert_called_with(["input", "keyevent", "KEYCODE_BACK"], None)

            # Already prefixed code KEYCODE_HOME should remain KEYCODE_HOME
            android.key_event("KEYCODE_HOME")
            mock_shell.assert_called_with(["input", "keyevent", "KEYCODE_HOME"], None)

            # Invalid characters should raise AdbError
            with self.assertRaises(android.AndroidError):
                android.key_event("BACK; rm -rf /")

    def test_launch_app_activity_formatting(self):
        with patch.object(android, "run_device_shell") as mock_shell:
            # Activity starting with dot
            android.launch_app("com.example.app", ".MainActivity")
            mock_shell.assert_called_with(["am", "start", "-W", "-n", "com.example.app/.MainActivity"], None)

            # Full activity path with dot prefix
            android.launch_app("com.example.app", "com.example.app.MainActivity")
            mock_shell.assert_called_with(["am", "start", "-W", "-n", "com.example.app/com.example.app.MainActivity"], None)

            # Activity already containing slash
            android.launch_app("com.example.app", "com.example.app/.MainActivity")
            mock_shell.assert_called_with(["am", "start", "-W", "-n", "com.example.app/.MainActivity"], None)

            # Simple activity name without dot
            android.launch_app("com.example.app", "MainActivity")
            mock_shell.assert_called_with(["am", "start", "-W", "-n", "com.example.app/.MainActivity"], None)

    def test_delete_file_protected_roots(self):
        # Exact root
        with self.assertRaises(android.AndroidError):
            android.delete_file("/system")

        # Subpaths under protected roots
        with self.assertRaises(android.AndroidError):
            android.delete_file("/system/bin/sh")

        with self.assertRaises(android.AndroidError):
            android.delete_file("/vendor/lib/libtest.so")

        with self.assertRaises(android.AndroidError):
            android.delete_file("/data/data/com.foo")

        with self.assertRaises(android.AndroidError):
            android.delete_file("/dev/block/bootdevice")

        # Relative paths
        with self.assertRaises(android.AndroidError):
            android.delete_file("sdcard/file.txt")

    def test_install_apk_multi_path_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            good_apk = Path(tmpdir) / "good.apk"
            good_apk.touch()
            not_apk = Path(tmpdir) / "bad.txt"
            not_apk.touch()

            # Second path is not .apk
            with self.assertRaises(android.AndroidError):
                android.install_apk(f"{good_apk},{not_apk}")

            # Second path outside allowed dirs
            outside_apk = Path("/etc/secret.apk")
            with self.assertRaises(android.AndroidError):
                android.install_apk(f"{good_apk},{outside_apk}")

    def test_resolve_serial(self):
        # 1 device online -> returns serial
        with patch.object(android, "_parse_devices_short", return_value=[("device1", "device")]):
            self.assertEqual(android.resolve_serial(None), "device1")

        # 0 devices online -> raises AdbError
        with patch.object(android, "_parse_devices_short", return_value=[]):
            with self.assertRaises(android.AndroidError):
                android.resolve_serial(None)

        # Multiple devices online -> raises AdbError
        with patch.object(android, "_parse_devices_short", return_value=[("d1", "device"), ("d2", "device")]):
            with self.assertRaises(android.AndroidError):
                android.resolve_serial(None)

        # Explicit serial passed -> returned as is
        self.assertEqual(android.resolve_serial("custom_device"), "custom_device")

    def test_tap_element_fallback_and_coords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            shot_file = Path(tmpdir) / "shot.png"
            shot_file.touch()

            # Set last screenshot path
            android._last_screenshot_path = str(shot_file)

            with patch.object(android, "_run_android", return_value="input tap 450 1200"):
                # Call without explicit path -> uses last screenshot
                resolved, coords = android.tap_element(None, "input tap #1")
                self.assertEqual(resolved, "input tap 450 1200")
                self.assertEqual(coords, (450, 1200))

    def test_mcp_err_flag(self):
        err_res = main._err("Test error", foo="bar")
        self.assertTrue(err_res.is_error)
        self.assertEqual(err_res.content[0].text, "Test error")
        self.assertEqual(err_res.structured_content, {"foo": "bar"})

    def test_get_layout_summary_in_text(self):
        mock_tree = [
            {
                "class": "android.widget.Button",
                "text": "Submit",
                "resource-id": "com.app:id/submit",
                "center": {"x": 500, "y": 1000},
                "interactions": ["click"],
            }
        ]
        with patch.object(android, "get_layout", return_value=mock_tree):
            result = main.get_layout()
            self.assertFalse(result.is_error)
            text = result.content[0].text
            self.assertIn("Submit", text)
            self.assertIn("(500,1000)", text)
            self.assertIn("com.app:id/submit", text)

    def test_open_url(self):
        with patch.object(android, "run_device_shell", return_value="Starting: Intent ...") as mock_shell:
            out = android.open_url("https://example.com")
            mock_shell.assert_called_with(
                ["am", "start", "-a", "android.intent.action.VIEW", "-d", "https://example.com"],
                None,
            )
            self.assertEqual(out, "Starting: Intent ...")

        # Disallowed characters in URL
        with self.assertRaises(android.AndroidError):
            android.open_url("https://example.com; rm -rf /")

    def test_wake_screen(self):
        with patch.object(android, "run_device_shell") as mock_shell:
            res = android.wake_screen()
            self.assertIn("awake", res)
            mock_shell.assert_any_call(["input", "keyevent", "KEYCODE_WAKEUP"], None)
            mock_shell.assert_any_call(["input", "keyevent", "82"], None)

    def test_current_app_parsing(self):
        dumpsys_window_sample = """
        WINDOW MANAGER WINDOWS (dumpsys window windows)
          mCurrentFocus=Window{8ab99e4 u0 com.android.settings/com.android.settings.Settings}
          mFocusedApp=AppWindowToken{...}
        """
        with patch.object(android, "run_device_shell", return_value=dumpsys_window_sample):
            info = android.current_app()
            self.assertEqual(info["package"], "com.android.settings")
            self.assertEqual(info["activity"], "com.android.settings.Settings")
            self.assertEqual(info["component"], "com.android.settings/com.android.settings.Settings")

    # ---- iOS Tests -------------------------------------------------------------

    def test_ios_resolve_developer_dir(self):
        with patch.dict(os.environ, {"DEVELOPER_DIR": "/Applications/Xcode.app/Contents/Developer"}):
            with patch("pathlib.Path.is_dir", return_value=True):
                self.assertEqual(str(ios.resolve_developer_dir()), "/Applications/Xcode.app/Contents/Developer")

    def test_ios_resolve_simulator(self):
        sample_sims = [
            {"name": "iPhone 16 Pro", "udid": "UDID-1", "state": "Shutdown", "isAvailable": True, "runtime": "iOS-18-0"},
            {"name": "iPhone 15", "udid": "UDID-2", "state": "Booted", "isAvailable": True, "runtime": "iOS-17-0"},
        ]
        with patch.object(ios, "list_simulators", return_value=sample_sims):
            # Resolve by exact UDID
            self.assertEqual(ios.resolve_simulator("UDID-1"), "UDID-1")
            # Resolve by exact name
            self.assertEqual(ios.resolve_simulator("iPhone 16 Pro"), "UDID-1")
            # Resolve auto (1 booted)
            self.assertEqual(ios.resolve_simulator(None), "UDID-2")

            # 0 booted
            with patch.object(ios, "list_simulators", return_value=[{"name": "iPhone 16", "udid": "U1", "state": "Shutdown"}]):
                with self.assertRaises(ios.IosError):
                    ios.resolve_simulator(None)

            # Multiple booted
            with patch.object(ios, "list_simulators", return_value=[
                {"name": "iPhone 16", "udid": "U1", "state": "Booted", "runtime": "iOS 18"},
                {"name": "iPhone 15", "udid": "U2", "state": "Booted", "runtime": "iOS 17"},
            ]):
                with self.assertRaises(ios.IosError):
                    ios.resolve_simulator(None)

    def test_ios_boot_and_shutdown(self):
        sample_sims = [
            {"name": "iPhone 16 Pro", "udid": "UDID-1", "state": "Shutdown", "isAvailable": True, "runtime": "iOS-18-0"},
        ]
        with patch.object(ios, "list_simulators", return_value=sample_sims):
            with patch.object(ios, "_run_simctl") as mock_simctl, patch("subprocess.run"):
                res = ios.boot_simulator("UDID-1", show_gui=False)
                self.assertIn("Booted simulator", res)
                mock_simctl.assert_called_with(["boot", "UDID-1"], timeout=60.0)

            with patch.object(ios, "_run_simctl") as mock_simctl:
                res = ios.shutdown_simulator("UDID-1")
                self.assertIn("shut down successfully", res)
                mock_simctl.assert_called_with(["shutdown", "UDID-1"], timeout=30.0)

    def test_ios_permission_validation(self):
        sample_sims = [{"name": "iPhone 16", "udid": "U1", "state": "Booted", "runtime": "iOS-18"}]
        with patch.object(ios, "list_simulators", return_value=sample_sims):
            with patch.object(ios, "_run_simctl") as mock_simctl:
                res = ios.set_permission("camera", "com.example.app", "grant", "U1")
                self.assertIn("grant", res.lower())
                mock_simctl.assert_called_with(["privacy", "U1", "grant", "camera", "com.example.app"], timeout=15.0)

            # Invalid service
            with self.assertRaises(ios.IosError):
                ios.set_permission("invalid_svc", "com.example.app", "grant", "U1")

            # Invalid action
            with self.assertRaises(ios.IosError):
                ios.set_permission("camera", "com.example.app", "hack", "U1")

            # Malformed bundle ID
            with self.assertRaises(ios.IosError):
                ios.set_permission("camera", "bad bundle; id", "grant", "U1")

    def test_ios_appearance_validation(self):
        sample_sims = [{"name": "iPhone 16", "udid": "U1", "state": "Booted", "runtime": "iOS-18"}]
        with patch.object(ios, "list_simulators", return_value=sample_sims):
            with patch.object(ios, "_run_simctl") as mock_simctl:
                res = ios.set_appearance("dark", "U1")
                self.assertIn("dark", res)
                mock_simctl.assert_called_with(["ui", "U1", "appearance", "dark"], timeout=15.0)

            with self.assertRaises(ios.IosError):
                ios.set_appearance("sepia", "U1")

    def test_ios_location_validation(self):
        sample_sims = [{"name": "iPhone 16", "udid": "U1", "state": "Booted", "runtime": "iOS-18"}]
        with patch.object(ios, "list_simulators", return_value=sample_sims):
            with patch.object(ios, "_run_simctl") as mock_simctl:
                res = ios.set_location(37.7749, -122.4194, "U1")
                self.assertIn("37.7749", res)
                mock_simctl.assert_called_with(["location", "U1", "set", "37.7749,-122.4194"], timeout=15.0)

            # Out of bounds lat
            with self.assertRaises(ios.IosError):
                ios.set_location(100.0, 0.0, "U1")

    def test_ios_press_button_validation(self):
        with patch.object(ios, "_run_applescript") as mock_as:
            res = ios.press_button_simulator("home")
            self.assertIn("Pressed 'home'", res)

            # Invalid button
            with self.assertRaises(ios.IosError):
                ios.press_button_simulator("self_destruct")

    def test_ios_physical_devices_parsing(self):
        sample_json = {
            "result": {
                "devices": [
                    {
                        "identifier": "00008110-001234567890",
                        "deviceProperties": {"name": "Alice's iPhone", "osVersionNumber": "18.1"},
                        "hardwareProperties": {"marketingName": "iPhone 15 Pro", "platform": "iOS"},
                        "connectionProperties": {"isPaired": True, "tunnelState": "connected"},
                    }
                ]
            }
        }
        with patch.object(ios, "_run_devicectl", return_value=sample_json):
            devs = ios.list_physical_devices()
            self.assertEqual(len(devs), 1)
            self.assertEqual(devs[0]["name"], "Alice's iPhone")
            self.assertEqual(devs[0]["modelName"], "iPhone 15 Pro")
            self.assertTrue(devs[0]["isPaired"])

    def test_ios_tools_registered(self):
        import asyncio
        tool_names = [t.name for t in asyncio.run(main.mcp.list_tools())]
        self.assertIn("ios_list_simulators", tool_names)
        self.assertIn("ios_boot_simulator", tool_names)
        self.assertIn("ios_shutdown_simulator", tool_names)
        self.assertIn("ios_screenshot", tool_names)
        self.assertIn("ios_tap", tool_names)
        self.assertIn("ios_swipe", tool_names)
        self.assertIn("ios_input_text", tool_names)
        self.assertIn("ios_press_button", tool_names)
        self.assertIn("ios_open_url", tool_names)
        self.assertIn("ios_launch_app", tool_names)
        self.assertIn("ios_terminate_app", tool_names)
        self.assertIn("ios_install_app", tool_names)
        self.assertIn("ios_uninstall_app", tool_names)
        self.assertIn("ios_set_appearance", tool_names)
        self.assertIn("ios_set_location", tool_names)
        self.assertIn("ios_set_permission", tool_names)
        self.assertIn("ios_set_status_bar", tool_names)
        self.assertIn("ios_send_push_notification", tool_names)
        self.assertIn("ios_add_media", tool_names)
        self.assertIn("ios_list_physical_devices", tool_names)
        self.assertIn("ios_device_info", tool_names)
        self.assertIn("ios_device_reboot", tool_names)
        self.assertIn("list_all_devices", tool_names)

    def test_unified_health_check(self):
        fake_android_health = {
            "adb_version": "1.0.41",
            "adb": "/path/to/adb",
            "android_cli_version": "1.0",
            "sdk_root": "/path/to/sdk",
            "device_count": 1,
            "devices": [{"serial": "emulator-5554", "state": "device", "model": "Pixel"}],
            "android_cli": "/path/to/android",
        }
        fake_ios_health = {
            "developer_dir": "/Applications/Xcode.app/Contents/Developer",
            "xcode_version": "Xcode 16.0",
            "simctl_available": True,
            "devicectl_available": True,
            "booted_simulators": [{"name": "iPhone 16", "runtime": "iOS 18", "udid": "SIM-1"}],
            "physical_devices": [{"name": "iPad", "modelName": "iPad Pro", "osVersion": "18.0", "identifier": "DEV-1"}],
        }
        with patch.object(android, "health", return_value=fake_android_health), patch.object(ios, "health", return_value=fake_ios_health):
            res = main.health_check()
            self.assertFalse(res.is_error)
            text = res.content[0].text
            self.assertIn("Android Environment", text)
            self.assertIn("emulator-5554", text)
            self.assertIn("iOS Environment", text)
            self.assertIn("iPhone 16", text)
            self.assertIn("iPad Pro", text)

    def test_unified_list_all_devices(self):
        fake_adb_devs = [{"serial": "emulator-5554", "state": "device", "model": "Pixel"}]
        fake_sims = [{"name": "iPhone 16", "runtime": "iOS 18", "udid": "SIM-1", "state": "Booted"}]
        fake_pdevs = [{"name": "iPhone 15", "modelName": "iPhone 15", "osVersion": "18.0", "identifier": "DEV-1"}]
        with patch.object(android, "list_devices", return_value=fake_adb_devs), \
             patch.object(ios, "list_simulators", return_value=fake_sims), \
             patch.object(ios, "list_physical_devices", return_value=fake_pdevs):
            res = main.list_all_devices()
            self.assertFalse(res.is_error)
            text = res.content[0].text
            self.assertIn("emulator-5554", text)
            self.assertIn("SIM-1", text)
            self.assertIn("DEV-1", text)

    def test_ios_get_layout_and_tap_element(self):
        sample_elements = [
            {
                "index": 1,
                "text": "Settings",
                "confidence": 0.99,
                "point_bounds": {"x": 100, "y": 200, "width": 80, "height": 30},
                "point_center": {"x": 140, "y": 215},
            },
            {
                "index": 2,
                "text": "General",
                "confidence": 0.98,
                "point_bounds": {"x": 100, "y": 250, "width": 80, "height": 30},
                "point_center": {"x": 140, "y": 265},
            },
        ]
        with patch.object(ios, "get_layout_simulator", return_value=sample_elements):
            res = main.ios_get_layout()
            self.assertFalse(res.is_error)
            text = res.content[0].text
            self.assertIn("Settings", text)
            self.assertIn("(140, 215)", text)
            self.assertIn("General", text)

        with patch.object(ios, "tap_simulator", return_value="Tapped Simulator at (140, 215)"), \
             patch.object(ios, "resolve_simulator", return_value="U1"):
            ios._LAST_LAYOUT_ELEMENTS = sample_elements
            # Tap by index
            msg, coords = ios.tap_element_simulator("#1", "U1")
            self.assertIn("Settings", msg)
            self.assertEqual(coords, (140, 215))

            # Tap by text
            msg, coords = ios.tap_element_simulator("General", "U1")
            self.assertIn("General", msg)
            self.assertEqual(coords, (140, 265))

            # Tap invalid element
            with self.assertRaises(ios.IosError):
                ios.tap_element_simulator("NonExistent", "U1")


if __name__ == "__main__":
    unittest.main()
