import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import android
import ios
import main


class TestDestructiveConfirm(unittest.TestCase):
    def test_uninstall_app_requires_confirm(self):
        with patch.object(android, "uninstall_app", return_value="OK") as mock_un:
            res = main.uninstall_app(package="com.example.app")
            self.assertTrue(res.is_error)
            self.assertIn("confirm=true", res.content[0].text)
            mock_un.assert_not_called()

            res = main.uninstall_app(package="com.example.app", confirm=True)
            self.assertFalse(res.is_error)
            mock_un.assert_called_once_with("com.example.app", None)

    def test_clear_app_data_requires_confirm(self):
        with patch.object(android, "clear_app_data", return_value="OK") as mock_cl:
            res = main.clear_app_data(package="com.example.app")
            self.assertTrue(res.is_error)
            mock_cl.assert_not_called()

            res = main.clear_app_data(package="com.example.app", confirm=True)
            self.assertFalse(res.is_error)
            mock_cl.assert_called_once_with("com.example.app", None)

    def test_delete_file_requires_confirm(self):
        with patch.object(android, "delete_file", return_value="deleted") as mock_del:
            res = main.delete_file(device_path="/sdcard/x.txt")
            self.assertTrue(res.is_error)
            mock_del.assert_not_called()

            res = main.delete_file(device_path="/sdcard/x.txt", confirm=True)
            self.assertFalse(res.is_error)
            mock_del.assert_called_once_with("/sdcard/x.txt", None)

    def test_file_delete_alias_passes_confirm(self):
        with patch.object(android, "delete_file", return_value="deleted") as mock_del:
            res = main.file_delete(device_path="/sdcard/x.txt")
            self.assertTrue(res.is_error)
            mock_del.assert_not_called()

            res = main.file_delete(device_path="/sdcard/x.txt", confirm=True)
            self.assertFalse(res.is_error)
            mock_del.assert_called_once_with("/sdcard/x.txt", None)

    def test_reboot_requires_confirm(self):
        with patch.object(android, "reboot", return_value="rebooting") as mock_rb:
            res = main.reboot()
            self.assertTrue(res.is_error)
            mock_rb.assert_not_called()

            res = main.reboot(confirm=True)
            self.assertFalse(res.is_error)
            mock_rb.assert_called_once_with(None, None)

    def test_ios_erase_requires_confirm(self):
        with patch.object(ios, "erase_simulator", return_value="wiped") as mock_erase:
            res = main.ios_erase_simulator(udid="U1")
            self.assertTrue(res.is_error)
            mock_erase.assert_not_called()

            res = main.ios_erase_simulator(udid="U1", confirm=True)
            self.assertFalse(res.is_error)
            mock_erase.assert_called_once_with("U1")

    def test_ios_uninstall_requires_confirm(self):
        with patch.object(ios, "uninstall_app_simulator", return_value="uninstalled") as mock_un:
            res = main.ios_uninstall_app(bundle_id="com.example.app")
            self.assertTrue(res.is_error)
            mock_un.assert_not_called()

            res = main.ios_uninstall_app(
                bundle_id="com.example.app", udid="U1", confirm=True
            )
            self.assertFalse(res.is_error)
            mock_un.assert_called_once_with("com.example.app", "U1")

    def test_ios_device_reboot_requires_confirm(self):
        with patch.object(ios, "reboot_device", return_value="rebooting") as mock_rb:
            res = main.ios_device_reboot(device_uuid="D1")
            self.assertTrue(res.is_error)
            mock_rb.assert_not_called()

            res = main.ios_device_reboot(device_uuid="D1", confirm=True)
            self.assertFalse(res.is_error)
            mock_rb.assert_called_once_with("D1")

    def test_require_confirm_helper(self):
        denied = main._require_confirm(False, "uninstall_app")
        self.assertIsNotNone(denied)
        self.assertTrue(denied.is_error)
        self.assertTrue(denied.structured_content.get("confirm_required"))
        self.assertIsNone(main._require_confirm(True, "uninstall_app"))


if __name__ == "__main__":
    unittest.main()
