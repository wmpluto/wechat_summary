"""Device connection manager for Android devices via uiautomator2."""

import uiautomator2

from wechat_summary.exceptions import DeviceNotFoundError, WeChatNotFoundError


class DeviceManager:
    """Manages connection to Android devices and WeChat verification."""

    def connect(self, serial=None):
        """
        Connect to an Android device via USB.

        Args:
            serial (str, optional): Device serial number. If None, auto-detects.

        Returns:
            Device: Connected uiautomator2 device object.

        Raises:
            DeviceNotFoundError: If no device found or connection fails.
        """
        try:
            if serial:
                device = uiautomator2.connect(serial)
            else:
                device = uiautomator2.connect()
            return device
        except Exception as e:
            raise DeviceNotFoundError(
                f"Failed to connect to device. Ensure USB debugging is enabled "
                f"and device is connected. Run 'adb devices' to check. Error: {e}"
            ) from e

    def check_wechat(self, device):
        """
        Check if WeChat (com.tencent.mm) is installed on device.

        Args:
            device: Connected uiautomator2 device object.

        Returns:
            bool: True if WeChat is installed, False otherwise.

        Raises:
            WeChatNotFoundError: If WeChat is not installed.
        """
        app_list = device.app_list()
        if "com.tencent.mm" not in app_list:
            raise WeChatNotFoundError(
                "WeChat (com.tencent.mm) is not installed on this device. "
                "Please install WeChat from Google Play Store or similar."
            )
        return True

    def get_device_info(self, device):
        """
        Get device information (model and Android version).

        Args:
            device: Connected uiautomator2 device object.

        Returns:
            str: Device info string in format "Model | Android Version".
        """
        info = device.info
        model = info.get("model", "Unknown")
        version = info.get("version", "Unknown")
        return f"{model} | Android {version}"

    def launch_wechat(self, device):
        """Launch WeChat and wait for it to be in foreground.

        Args:
            device: Connected uiautomator2 device object.

        Returns:
            bool: True if WeChat is now in foreground.
        """
        import time

        device.app_start("com.tencent.mm")
        time.sleep(2.0)
        current = device.app_current()
        return current.get("package") == "com.tencent.mm"

    def disconnect(self, device):
        """
        Disconnect from device.

        Args:
            device: Connected uiautomator2 device object.
        """
        # uiautomator2 doesn't require explicit disconnect in most cases
        # but we provide this for API completeness
        pass
