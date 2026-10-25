"""选区捕获层（Windows 系统级划词，M2）。

触发：低层鼠标钩子检测"拖拽后释放" gesture（pynput）。
取词：UIA(uiautomation) → 剪贴板回退（先缓存再还原，防破坏用户剪贴板）。
      IAccessible 与光标形状降智留作后续（剪贴板回退已覆盖多数场景）。
线程模型：SelectionMonitor 只在后台线程判定"是否划选"，发坐标信号；
          真正取词（含剪贴板）回到 Qt 主线程执行，保证 QClipboard 线程安全。
"""
import ctypes
import os
import time

from PySide6.QtCore import QObject, Signal

from .actions import clipboard_get_text

DRAG_THRESHOLD = 6  # px，超过才算拖选

# 取词重入防御：extract_clipboard 的等待循环会 processEvents()，期间鼠标钩子
# 可能再次触发划词 → on_selection → extract_selected_text 递归进入，嵌套
# 发送 Ctrl+C/剪贴板抖动。进程内同一时刻只允许一次取词。
_EXTRACTING = False


def prefill_from_clipboard() -> str:
    """M1 便利：热键唤起时用剪贴板预填。"""
    try:
        return clipboard_get_text().strip()
    except Exception:
        return ""


# ---------- 取词（在主线程调用） ----------
def extract_uia():
    """用 UI Automation 读当前焦点元素的选中文本。失败/无选中返回 None。"""
    if os.name != "nt":
        return None
    try:
        import uiautomation as auto
    except Exception:
        return None
    try:
        focus = auto.GetFocusedControl()
    except Exception:
        return None
    if focus is None:
        return None
    controls = [focus]
    try:
        controls += list(focus.GetChildren())
    except Exception:
        pass
    for c in controls:
        try:
            tp = c.GetTextPattern()
        except Exception:
            tp = None
        if not tp:
            continue
        try:
            sels = tp.GetSelection()
        except Exception:
            sels = None
        if sels:
            parts = []
            for r in sels:
                try:
                    parts.append(r.GetText(-1) or "")
                except Exception:
                    pass
            text = "\n".join(p for p in parts if p)
            if text.strip():
                return text
    return None


# ---------- 系统状态探针（best-effort；真实行为待真机确认） ----------
def cursor_kind():
    """当前光标形状：ibeam / arrow / hand / custom / unknown。"""
    if os.name != "nt":
        return "unknown"
    try:
        class _CURSORINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint),
                        ("hCursor", ctypes.c_void_p), ("ptScreenPos", ctypes.c_long * 2)]
        ci = _CURSORINFO()
        ci.cbSize = ctypes.sizeof(_CURSORINFO)
        if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(ci)):
            return "unknown"
        hcur = ci.hCursor
        for name, resid in (("ibeam", 32513), ("arrow", 32512), ("hand", 32649)):
            std = ctypes.windll.user32.LoadCursorW(None, resid)
            if std and int(std) == int(hcur):
                return name
        return "custom"
    except Exception:
        return "unknown"


def should_attempt_clipboard(cursor, program, exclude_cursor_detect):
    """是否走剪贴板回退的降智判定（纯函数，便于测试）。

    依据 selection-hook（PromptPop 复用的取词参考实现）最佳实践：只有 I-beam
    （文本光标）才走剪贴板回退；arrow/hand/custom 明确不是文本选择，跳过可避免
    非文本拖拽（拖图片/窗口/表格非文本选区）误弹工具条；unknown（光标检测失败）
    保守走，避免漏取；自定义光标程序（如 Acrobat，在名单内）强制走。"""
    if program and any(x.lower() in program.lower() for x in exclude_cursor_detect):
        return True  # 自定义光标的程序（如 Acrobat）跳过降智
    return cursor in ("ibeam", "unknown")


def should_capture_selection(program, exclude_list):
    """划词监听是否应真正取词（纯函数，便于测试）。

    这些程序里「左键拖拽」通常是移动文件/窗口而非选文字，取词会误触发
    剪贴板抖动与工具条误弹，直接跳过。program 为前台 exe 名（小写）。"""
    if not program:
        return True
    p = program.lower()
    for ex in (exclude_list or []):
        if ex and ex.lower() in p:
            return False
    return True


def is_fullscreen_exclusive():
    """是否处于全屏游戏/演示模式（此时跳过划词，避免干扰）。best-effort。"""
    if os.name != "nt":
        return False
    try:
        QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE = 3, 6
        state = ctypes.c_int()
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return state.value in (QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)
    except Exception:
        pass
    return False


def foreground_program():
    """当前前台程序名（小写 exe），用于逐应用 fine-tuned。取不到返回 ""。"""
    if os.name != "nt":
        return ""
    try:
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(260)
        size = wt.DWORD(260)
        ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        ctypes.windll.kernel32.CloseHandle(h)
        return os.path.basename(buf.value).lower() if ok else ""
    except Exception:
        return ""


def _send_ctrl_insert():
    user32 = ctypes.windll.user32
    VK_CONTROL, VK_INSERT, KEYUP = 0x11, 0x2D, 2
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_INSERT, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_INSERT, 0, KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)


def _send_ctrl_c():
    user32 = ctypes.windll.user32
    VK_CONTROL, VK_C, KEYUP = 0x11, 0x43, 2
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_C, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_C, 0, KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)


def _clipboard_get_html():
    try:
        from PySide6.QtWidgets import QApplication
        m = QApplication.clipboard().mimeData()
        return m.html() if (m and m.hasHtml()) else ""
    except Exception:
        return ""


def _clipboard_snapshot():
    """完整快照当前剪贴板的所有 MIME 格式（含 Office 私有格式/图片等），
    用于取词结束后原样还原，避免只还原 text+html 导致其它格式丢失或损坏。
    返回 QMimeData 克隆；失败返回 None（调用方走 text+html 兜底）。"""
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QMimeData
        src = QApplication.clipboard().mimeData()
        if src is None:
            return None
        md = QMimeData()
        for fmt in src.formats():
            try:
                md.setData(fmt, src.data(fmt))
            except Exception:
                pass
        return md
    except Exception:
        return None


def _clipboard_restore_full(md):
    try:
        if md is None:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setMimeData(md)
    except Exception:
        pass


def _clipboard_restore(text, html):
    try:
        if html:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QMimeData
            md = QMimeData()
            if text:
                md.setText(text)
            md.setHtml(html)
            QApplication.clipboard().setMimeData(md)
        else:
            from . import actions
            actions.clipboard_set_text(text)
    except Exception:
        pass


def pick_clipboard_delay(program, cfg_data):
    """选择剪贴板读取延时（纯函数，便于测试）。

    默认 0.12s；对「多次写剪贴板」的程序（如 Acrobat）多等一会（0.28s）。
    两个值均可经配置 clipboard_delay_default / clipboard_delay_slow 调整。
    取词在主线程执行，此延时会短暂冻结事件循环——已尽量压低默认值。
    """
    cfg_data = cfg_data or {}
    from .util import safe_float
    default = safe_float(cfg_data.get("clipboard_delay_default"), 0.12)
    slow = safe_float(cfg_data.get("clipboard_delay_slow"), 0.28)
    if program and any(x.lower() in program.lower()
                       for x in cfg_data.get("clipboard_delay_read", [])):
        return slow
    return default


def _clipboard_seq():
    """当前剪贴板序列号（Windows Vista+）。内容变化时递增；用于「等目标程序写入」。"""
    if os.name != "nt":
        return 0
    try:
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def _wait_clipboard_change(prev_seq, timeout, seq_getter=None, sleeper=None,
                           poll_interval=0.008):
    """等待剪贴板内容变化（目标程序响应了 Ctrl+C）。

    相比固定 time.sleep：①目标程序一写入就返回，通常远快于 120ms；
    ②等待期间不断 processEvents()，浮窗/托盘不冻结。

    seq_getter/sleeper 可注入（测试用）。返回是否检测到变化
    （False 表示超时，调用方仍照常读一次剪贴板）。
    """
    from PySide6.QtWidgets import QApplication
    seq_getter = seq_getter or _clipboard_seq
    sleeper = sleeper or time.sleep
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        try:
            QApplication.processEvents()
        except Exception:
            pass
        if seq_getter() != prev_seq:
            return True
        if time.monotonic() >= deadline:
            return False
        sleeper(poll_interval)   # 8ms 粒度：足够灵敏，又不至于空转烧 CPU


def extract_clipboard(cfg_data=None, program=""):
    """剪贴板回退：先完整快照(所有 MIME 格式)→Ctrl+Insert→Ctrl+C 两段式→读→原样还原。
    依据 selection-hook（两段式更稳）与 Cherry Studio 踩坑（必须还原，含富文本）；
    完整快照可保留 Office 等私有格式，避免只还原 text+html 造成剪贴板损坏。"""
    if os.name != "nt":
        return None
    from . import actions
    cfg_data = cfg_data or {}
    snapshot = _clipboard_snapshot()           # 完整 MIME 快照（保真还原）
    # 快照失败时的 text+html 兜底
    backup_text = "" if snapshot is not None else actions.clipboard_get_text()
    backup_html = "" if snapshot is not None else _clipboard_get_html()
    delay = pick_clipboard_delay(program, cfg_data)
    got = None
    try:
        try:
            actions.clipboard_set_text("")     # 清空，便于判定「有新内容写入」
        except Exception:
            pass
        seq0 = _clipboard_seq()                # 清空后的基线序列号
        _send_ctrl_insert()
        _wait_clipboard_change(seq0, delay)
        cand = actions.clipboard_get_text()
        if not (cand and cand.strip()):
            seq1 = _clipboard_seq()
            _send_ctrl_c()
            _wait_clipboard_change(seq1, delay)
            cand = actions.clipboard_get_text()
        if cand and cand.strip():
            got = cand
    finally:
        if snapshot is not None:
            _clipboard_restore_full(snapshot)
        else:
            _clipboard_restore(backup_text, backup_html)
    return got


def extract_selected_text(cfg_data=None, program=""):
    """返回 (text, method)。method ∈ uia / clipboard / none。
    IAccessible 层预留（剪贴板回退已覆盖多数老应用），真实覆盖率待确认。
    剪贴板回退前先做光标降智：非文本光标（arrow/hand/custom）跳过，减少误触发。
    重入（等待期间再次触发）直接返回 none，防止嵌套剪贴板抖动。"""
    global _EXTRACTING
    cfg_data = cfg_data or {}
    if _EXTRACTING:
        return "", "none"
    _EXTRACTING = True
    try:
        t = extract_uia()
        if t and t.strip():
            return t, "uia"
        cursor = cursor_kind()
        if not should_attempt_clipboard(cursor, program,
                                       cfg_data.get("exclude_cursor_detect", [])):
            return "", "none"
        t = extract_clipboard(cfg_data, program)
        if t and t.strip():
            return t, "clipboard"
        return "", "none"
    finally:
        _EXTRACTING = False


# ---------- 划选手势监听（后台线程） ----------
class SelectionMonitor(QObject):
    selection_made = Signal(int, int, str)  # 拖选释放时的 x, y, 前台程序名

    def __init__(self, enabled_getter=None):
        super().__init__()
        self._enabled_getter = enabled_getter or (lambda: True)
        self._pressed = False
        self._moved = False
        self._start = (0, 0)
        self._listener = None

    def start(self):
        if self._listener is not None:
            return
        try:
            from pynput import mouse

            def on_click(x, y, button, pressed):
                if button != mouse.Button.left or not self._enabled_getter():
                    return
                if pressed:
                    self._pressed = True
                    self._moved = False
                    self._start = (x, y)
                else:
                    was_drag = self._pressed and self._moved
                    self._pressed = False
                    if was_drag and not is_fullscreen_exclusive():
                        self.selection_made.emit(int(x), int(y), foreground_program())

            def on_move(x, y):
                if not self._enabled_getter() or not self._pressed:
                    return
                if (abs(x - self._start[0]) > DRAG_THRESHOLD
                        or abs(y - self._start[1]) > DRAG_THRESHOLD):
                    self._moved = True

            self._listener = mouse.Listener(on_click=on_click, on_move=on_move)
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:  # noqa: BLE001
            print("[selection] 监听启动失败：", e)

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
