"""全局热键管理。

Windows：使用系统级 ``RegisterHotKey`` + Qt ``QAbstractNativeEventFilter`` 接收
``WM_HOTKEY``。相比 pynput 的 ``WH_KEYBOARD_LL`` 低级钩子：

* 由操作系统直接派发，不受 Chromium / Electron / 游戏等「吞掉键盘钩子」的
  程序焦点影响（这是 pynput 在浏览器/编辑器中偶尔唤起失灵的根因）；
* 必须在运行消息循环的线程（Qt 主线程）注册，与 Qt 事件循环天然契合；
* 注册失败（被其它程序占用）可立即拿到系统错误码，给出明确提示。

非 Windows（仅开发/跨平台兜底）：回退到 pynput。

对外暴露：
* ``parse_combo(combo)``  —— pynput 规范格式 → (fsModifiers, vk)，纯函数可单测；
* ``create_hotkey_manager()`` —— 按平台返回管理器（均含 ``activated`` 信号、
  ``register(combo) -> (ok, err)``、``unregister()``）。
"""
import itertools
import sys
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal, QAbstractNativeEventFilter, QTimer
from PySide6.QtWidgets import QApplication

# ---------- Win32 常量 ----------
MOD_ALT = 0x1
MOD_CONTROL = 0x2
MOD_SHIFT = 0x4
MOD_WIN = 0x8
MOD_NOREPEAT = 0x4000          # 长按不自动重复触发
WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409   # 0x57F

_WIN_MOD = {"<ctrl>": MOD_CONTROL, "<shift>": MOD_SHIFT,
            "<alt>": MOD_ALT, "<cmd>": MOD_WIN}
_VK = {
    "<space>": 0x20, "<tab>": 0x09, "<enter>": 0x0D, "<esc>": 0x1B,
    "<escape>": 0x1B, "<backspace>": 0x08, "<delete>": 0x2E, "<home>": 0x24,
    "<end>": 0x23, "<up>": 0x26, "<down>": 0x28, "<left>": 0x25, "<right>": 0x27,
    "<pageup>": 0x21, "<pagedown>": 0x22, "<insert>": 0x2D,
}
# 说明：validate_hotkey 目前只产出「字母数字 / F1–F12 / 上表特殊键 / 修饰键」，
# 因此这里的 <insert>/<backtick> 属预留（parse_combo 多认一些无害），
# 但绝不能反过来：validate 能产出的 token，parse_combo 必须全都认识（见 tests/test_hotkey.py 的往返测试）。
for _i in range(1, 13):
    _VK["<f%d>" % _i] = 0x70 + (_i - 1)   # F1=0x70 … F12=0x7B


def parse_combo(combo):
    """pynput 规范格式（``<ctrl>+<shift>+space``）→ ``(fsModifiers, vk)``。

    非法（缺修饰键 / 缺主键 / 含未知键 / 格式错误）一律返回 ``(None, None)``。
    ``fsModifiers`` 已并入 ``MOD_NOREPEAT``，避免长按反复触发。
    纯函数、不触碰任何 Win32 调用，便于单测。
    """
    if not combo or not str(combo).strip():
        return None, None
    parts = [p.strip().lower() for p in str(combo).split("+")]
    if len(parts) < 2:
        return None, None
    mods = 0
    vk = None
    for p in parts:
        if p in _WIN_MOD:
            mods |= _WIN_MOD[p]
        elif p in _VK:
            vk = _VK[p]
        # 仅 ASCII 单字可作键名（与 util._norm_token 对齐）：
        # 中文/全角单字 isalnum() 为真，会把「ctrl+加」注册成无效组合
        elif len(p) == 1 and p.isascii() and p.isalnum():
            vk = ord(p.upper())
        else:
            return None, None
    if vk is None or mods == 0:
        return None, None
    return mods | MOD_NOREPEAT, vk


def _user32():
    """返回封装对象：RegisterHotKey/UnregisterHotKey 走 user32，
    GetLastError 走 kernel32（GetLastError 不在 user32 导出表）。

    返回单例，便于单测用 ``hotkey._user32 = lambda: Fake`` 整体替换。
    """
    if getattr(_user32, "_inst", None) is None:
        dll = ctypes.windll.user32
        dll.RegisterHotKey.argtypes = (wintypes.HWND, wintypes.INT,
                                       wintypes.UINT, wintypes.UINT)
        dll.RegisterHotKey.restype = wintypes.BOOL
        dll.UnregisterHotKey.argtypes = (wintypes.HWND, wintypes.INT)
        dll.UnregisterHotKey.restype = wintypes.BOOL
        kern = ctypes.windll.kernel32

        class _U32:
            def RegisterHotKey(self, *a):
                return dll.RegisterHotKey(*a)

            def UnregisterHotKey(self, *a):
                return dll.UnregisterHotKey(*a)

            def GetLastError(self):
                return kern.GetLastError()

        _user32._inst = _U32()
    return _user32._inst




class _HotkeyFilter(QAbstractNativeEventFilter):
    """在 Qt 事件循环里截获 WM_HOTKEY。"""

    def __init__(self, mgr):
        super().__init__()
        self._mgr = mgr

    def nativeEventFilter(self, eventType, message):
        et = eventType
        if isinstance(et, bytes):
            et = et.decode("ascii", "ignore")
        # Windows 平台 eventType 形如 "windows_generic_MSG" / "windows_dispatcher_MSG"
        if et and "windows" in et and "msg" in et.lower():
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._mgr._id:
                    # 抛回主线程事件循环执行，避免重入
                    QTimer.singleShot(0, self._mgr.activated.emit)
            except Exception:   # noqa: BLE001 — 解析异常不应影响其它事件
                pass
        return False


# 热键 id 走全局自增：同一线程内多个 manager 若都用 id=1，第二个 RegisterHotKey
# 会与第一个冲突/互相顶替。生产路径只创建一个 manager，但 id 唯一化是廉价的健壮性。
_id_seq = itertools.count(1)


class WinHotkeyManager(QObject):
    """Windows：RegisterHotKey 实现。"""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._id = next(_id_seq)
        self._registered = False
        self._combo = None
        self._filter = _HotkeyFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filter)

    def dispose(self):
        """注销热键 + 摘掉事件过滤器（不再需要时/退出时调用）。

        只 unregister 不摘过滤器也没错（过滤器只在本 id 命中时才发信号），
        但长期持有会让 QApplication 一直强引用本对象——显式摘掉更干净。
        """
        self.unregister()
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeNativeEventFilter(self._filter)
            except Exception:   # noqa: BLE001
                pass

    def register(self, combo):
        """注册热键。返回 ``(ok, err_msg)``。"""
        self.unregister()
        mods, vk = parse_combo(combo)
        if mods is None:
            return False, "热键格式非法"
        u = _user32()
        if not u.RegisterHotKey(None, self._id, mods, vk):
            err = u.GetLastError()
            if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                return False, "该热键已被其它程序占用，请换一个组合"
            return False, "热键注册失败（系统错误 %d）" % err
        self._registered = True
        self._combo = combo
        return True, ""

    def unregister(self):
        if self._registered:
            try:
                _user32().UnregisterHotKey(None, self._id)
            except Exception:   # noqa: BLE001
                pass
            self._registered = False


class PynputHotkeyManager(QObject):
    """非 Windows 兜底：沿用 pynput 的 GlobalHotKeys。"""

    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listener = None

    def register(self, combo):
        self.unregister()
        try:
            from pynput import keyboard

            def on_activate():
                self.activated.emit()

            hk = keyboard.GlobalHotKeys({combo: on_activate})
            hk.daemon = True
            hk.start()
            self._listener = hk
            return True, ""
        except Exception as e:   # noqa: BLE001
            return False, "热键启动失败：%s" % e

    def unregister(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:   # noqa: BLE001
                pass
            self._listener = None

    def dispose(self):
        """与 WinHotkeyManager 保持同一接口（非 Windows 路径无需摘事件过滤器）。"""
        self.unregister()


def create_hotkey_manager(parent=None):
    """按平台创建热键管理器。"""
    if sys.platform.startswith("win"):
        return WinHotkeyManager(parent)
    return PynputHotkeyManager(parent)
