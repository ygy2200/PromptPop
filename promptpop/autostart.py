"""Windows 开机自启（HKCU ...\\Run 项）。"""
import os
import sys

APP_NAME = "PromptPop"
_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _entry_command():
    if getattr(sys, "frozen", False):
        return sys.executable  # 打包后的 exe
    main_py = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else "main.py"
    return '"%s" "%s"' % (sys.executable, main_py)


def is_enabled():
    if os.name != "nt":
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_PATH)
        try:
            winreg.QueryValueEx(k, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(k)
    except Exception:
        return False


def enable():
    if os.name != "nt":
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_PATH, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _entry_command())
        winreg.CloseKey(k)
        return True
    except Exception as e:  # noqa: BLE001
        print("[autostart] enable failed:", e)
        return False


def disable():
    if os.name != "nt":
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_PATH, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(k, APP_NAME)
        except FileNotFoundError:
            pass
        winreg.CloseKey(k)
        return True
    except Exception as e:  # noqa: BLE001
        print("[autostart] disable failed:", e)
        return False
