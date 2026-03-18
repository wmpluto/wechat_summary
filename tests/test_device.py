"""Tests for device connection manager."""

import pytest
from unittest.mock import MagicMock, patch

from wechat_summary.device import DeviceManager, DeviceNotFoundError, WeChatNotFoundError


class TestDeviceManager:
    """Test suite for DeviceManager class."""

    def test_connect_success(self, mock_device):
        """Test successful device connection."""
        with patch("wechat_summary.device.uiautomator2") as mock_u2:
            mock_u2.connect.return_value = mock_device
            
            manager = DeviceManager()
            device = manager.connect()
            
            assert device is not None
            mock_u2.connect.assert_called_once()

    def test_connect_with_serial(self, mock_device):
        """Test device connection with specific serial number."""
        with patch("wechat_summary.device.uiautomator2") as mock_u2:
            mock_u2.connect.return_value = mock_device
            
            manager = DeviceManager()
            device = manager.connect(serial="emulator-5554")
            
            assert device is not None
            mock_u2.connect.assert_called_once_with("emulator-5554")

    def test_connect_no_device(self):
        """Test connection fails when no device available."""
        with patch("wechat_summary.device.uiautomator2") as mock_u2:
            mock_u2.connect.side_effect = Exception("Cannot connect to device")
            
            manager = DeviceManager()
            with pytest.raises(DeviceNotFoundError) as exc_info:
                manager.connect()
            
            assert "USB" in str(exc_info.value) or "device" in str(exc_info.value).lower()

    def test_check_wechat_installed(self, mock_device):
        """Test WeChat installation check when app is installed."""
        mock_device.app_list.return_value = ["com.tencent.mm", "com.android.settings"]
        
        manager = DeviceManager()
        is_installed = manager.check_wechat(mock_device)
        
        assert is_installed is True

    def test_check_wechat_not_installed(self, mock_device):
        """Test WeChat installation check when app is not installed."""
        mock_device.app_list.return_value = ["com.android.settings", "com.android.chrome"]
        
        manager = DeviceManager()
        with pytest.raises(WeChatNotFoundError) as exc_info:
            manager.check_wechat(mock_device)
        
        assert "com.tencent.mm" in str(exc_info.value) or "WeChat" in str(exc_info.value)

    def test_get_device_info(self, mock_device):
        """Test getting device information."""
        mock_device.info = {
            "model": "Xiaomi Redmi Note 11",
            "version": "12",
            "displayHeight": 1920,
            "displayWidth": 1080,
        }
        
        manager = DeviceManager()
        info = manager.get_device_info(mock_device)
        
        assert isinstance(info, str)
        assert "Xiaomi Redmi Note 11" in info
        assert "12" in info

    def test_get_device_info_format(self, mock_device):
        """Test device info returns model + version string."""
        mock_device.info = {
            "model": "Samsung Galaxy S21",
            "version": "13",
        }
        
        manager = DeviceManager()
        info = manager.get_device_info(mock_device)
        
        # Should be in format "Model | Android Version"
        assert "|" in info or "Android" in info or "13" in info

    def test_disconnect(self, mock_device):
        """Test device disconnection."""
        manager = DeviceManager()
        # Should not raise any exception
        manager.disconnect(mock_device)
        
        # Verify device methods were called (if applicable)
        # For now, just verify it doesn't crash

    def test_connect_auto_detect_no_serial(self, mock_device):
        """Test auto-detection when no serial provided."""
        with patch("wechat_summary.device.uiautomator2") as mock_u2:
            mock_u2.connect.return_value = mock_device
            
            manager = DeviceManager()
            device = manager.connect(serial=None)
            
            assert device is not None
            # Should call connect without serial (auto-detect)
            mock_u2.connect.assert_called_once()

    def test_check_wechat_with_multiple_apps(self, mock_device):
        """Test WeChat detection among many installed apps."""
        mock_device.app_list.return_value = [
            "com.android.settings",
            "com.android.chrome",
            "com.tencent.mm",
            "com.whatsapp",
            "com.facebook.katana",
        ]
        
        manager = DeviceManager()
        is_installed = manager.check_wechat(mock_device)
        
        assert is_installed is True

    def test_device_info_with_missing_fields(self, mock_device):
        """Test device info extraction with minimal fields."""
        mock_device.info = {
            "model": "Generic Device",
            "version": "11",
        }
        
        manager = DeviceManager()
        info = manager.get_device_info(mock_device)
        
        assert isinstance(info, str)
        assert len(info) > 0

    def test_connect_then_check_wechat_flow(self, mock_device):
        """Test typical flow: connect -> check WeChat."""
        with patch("wechat_summary.device.uiautomator2") as mock_u2:
            mock_u2.connect.return_value = mock_device
            mock_device.app_list.return_value = ["com.tencent.mm"]
            
            manager = DeviceManager()
            device = manager.connect()
            is_installed = manager.check_wechat(device)
            
            assert device is not None
            assert is_installed is True

    def test_connect_then_get_info_flow(self, mock_device):
        """Test typical flow: connect -> get device info."""
        with patch("wechat_summary.device.uiautomator2") as mock_u2:
            mock_u2.connect.return_value = mock_device
            mock_device.info = {
                "model": "Test Device",
                "version": "12",
            }
            
            manager = DeviceManager()
            device = manager.connect()
            info = manager.get_device_info(device)
            
            assert device is not None
            assert isinstance(info, str)
            assert "Test Device" in info
