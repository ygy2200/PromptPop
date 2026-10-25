"""动作层：复制 / 替换（Replace）。

Replace = 写剪贴板 + 恢复原前台窗口焦点 + 模拟 Ctrl+V。
参考 UniClipboard quick_panel 的 restore_previous_foreground + simulate_paste。
"""
import ctypes
import os
import time


def clipboard_set_text(text: str):
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText(text)


def clipboard_get_text() -> str:
    from PySide6.QtWidgets import QApplication
    return QApplication.clipboard().text() or ""


def get_foreground_hwnd():
    """弹窗出现前调用，记下原前台窗口句柄（Windows）。"""
    if os.name != "nt":
        return None
    try:
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def _is_valid_hwnd(hwnd):
    """句柄是否还指向一个有效窗口（可能已被关闭）。"""
    if not hwnd or os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.user32.IsWindow(hwnd))
    except Exception:
        return False


def _is_own_window(hwnd):
    """是不是 PromptPop 自己的窗口。

    若把焦点恢复到自己（浮窗/工具条刚关闭时 GetForegroundWindow 可能记成自己），
    Ctrl+V 会粘到自己的输入框里，表现为「替换没生效」。
    """
    if not hwnd or os.name != "nt":
        return False
    try:
        pid = ctypes.windll.kernel32.GetCurrentProcessId()
        owner_pid = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        # GetWindowThreadProcessId 返回的是线程 ID，需要用 GetProcessIdOfThread 换算
        return ctypes.windll.kernel32.GetProcessIdOfThread(owner_pid) == pid
    except Exception:
        return False


def _force_foreground(hwnd):
    """恢复目标窗口为前台。返回是否成功（失败时不应继续模拟粘贴）。"""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    cur = kernel32.GetCurrentThreadId()
    tgt = user32.GetWindowThreadProcessId(hwnd, None)
    # 临时接入目标线程输入队列，绕过系统"禁止抢焦点"限制
    user32.AttachThreadInput(tgt, cur, True)
    ok = bool(user32.SetForegroundWindow(hwnd))
    try:
        user32.BringWindowToTop(hwnd)
    except Exception:
        pass
    user32.AttachThreadInput(tgt, cur, False)
    if not ok:
        return False
    # 确认焦点真的过去了（SetForegroundWindow 在部分场景会静默失败）
    time.sleep(0.02)
    try:
        return int(user32.GetForegroundWindow()) == int(hwnd)
    except Exception:
        return False


def _send_ctrl_v():
    user32 = ctypes.windll.user32
    VK_CONTROL, VK_V, KEYUP = 0x11, 0x56, 2
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_V, 0, KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYUP, 0)


def is_current_elevated():
    """本进程是否以管理员（高完整性）运行。

    Windows UIPI 限制：普通完整性进程无法向高完整性（管理员）窗口发送
    模拟输入，SetForegroundWindow/Ctrl+V 会静默失效。用于给自动粘贴失败
    更具体的提示（见 overlay._replace_fail_msg）。
    """
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_target_elevated(hwnd):
    """目标窗口所在进程是否以管理员运行（best-effort）。

    用于区分「自动粘贴失败」的原因：若目标是管理员且自身不是，可给出
    「请手动 Ctrl+V 或把本程序也以管理员运行」的可执行指引，而非笼统的
    「未能定位原窗口」。非 Windows / 句柄无效时保守返回 False。
    """
    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        PROCESS_QUERY_INFORMATION = 0x0400
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid.value)
        if not h:
            return False
        TOKEN_QUERY = 0x0008
        htok = ctypes.c_void_p()
        if not kernel32.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(htok)):
            kernel32.CloseHandle(h)
            return False
        TokenElevation = 20
        elev = ctypes.c_int()
        dw = ctypes.c_ulong()
        ok = kernel32.GetTokenInformation(
            htok, TokenElevation, ctypes.byref(elev),
            ctypes.sizeof(elev), ctypes.byref(dw))
        kernel32.CloseHandle(htok)
        kernel32.CloseHandle(h)
        return bool(ok) and bool(elev.value)
    except Exception:
        return False


def replace_selection(text: str, owner_hwnd=None) -> bool:
    """把 text 粘贴回原窗口。返回是否真正执行了模拟粘贴。

    必须先确认目标窗口有效、不是自己的窗口、且焦点真的切过去了——
    否则会出现「提示已替换，其实粘到了自己输入框里」的假成功。
    粘贴后再比对一次前台窗口，防止 0.12s 间隙被输入法/UAC/Toast 抢焦点。
    成功时还原用户原有剪贴板（避免吞掉用户先前的复制内容）；
    失败时不还原，保留新文本供用户按提示手动 Ctrl+V。
    """
    old = clipboard_get_text()
    clipboard_set_text(text)
    if os.name != "nt":
        return False  # 非 Windows：仅复制到剪贴板，交由用户手动粘贴
    if not _is_valid_hwnd(owner_hwnd) or _is_own_window(owner_hwnd):
        return False
    time.sleep(0.05)
    if not _force_foreground(owner_hwnd):
        return False
    time.sleep(0.12)
    _send_ctrl_v()
    time.sleep(0.12)
    focus = _focus_still_on(owner_hwnd)
    if focus:
        # 成功：还原用户原剪贴板（最佳实践：粘贴后恢复，避免丢失用户原有内容）
        try:
            clipboard_set_text(old)
        except Exception:
            pass
    return focus


def _focus_still_on(hwnd):
    """粘贴后焦点是否仍在目标窗口（被抢焦点则视为失败）。"""
    if os.name != "nt" or not hwnd:
        return False
    try:
        return ctypes.windll.user32.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _has_text_selection(hwnd=None):
    """目标窗口当前是否有文本选区（best-effort）。

    用于「插入」：无选区时不发 Right 键，避免光标偏移一位。
    UIA 拿不到（终端/自绘控件等）时保守返回 True——保持原有折叠选区行为，
    不因探测失败改变默认语义。
    """
    if os.name != "nt":
        return True
    try:
        from .capture import extract_uia
        return bool(extract_uia())
    except Exception:
        return True


def _send_right():
    user32 = ctypes.windll.user32
    VK_RIGHT, KEYUP = 0x27, 2
    user32.keybd_event(VK_RIGHT, 0, 0, 0)
    time.sleep(0.02)
    user32.keybd_event(VK_RIGHT, 0, KEYUP, 0)


def insert_after(text: str, owner_hwnd=None) -> bool:
    """在原文末尾后插入（有选区则折叠到末尾，无选区则就地粘贴），不覆盖原文。

    无选区时不能发 Right 键——那会把光标右移一位，内容插到错误位置。
    成功时同样还原用户原有剪贴板。
    """
    old = clipboard_get_text()
    clipboard_set_text(text)
    if os.name != "nt":
        return False
    if not _is_valid_hwnd(owner_hwnd) or _is_own_window(owner_hwnd):
        return False
    time.sleep(0.05)
    if not _force_foreground(owner_hwnd):
        return False
    time.sleep(0.12)
    if _has_text_selection(owner_hwnd):
        _send_right()   # 有选区：折叠到末尾
        time.sleep(0.03)
    _send_ctrl_v()
    time.sleep(0.12)
    focus = _focus_still_on(owner_hwnd)
    if focus:
        try:
            clipboard_set_text(old)
        except Exception:
            pass
    return focus
