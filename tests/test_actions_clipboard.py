"""Replace/Insert 剪贴板还原 + 管理员窗口失败提示 测试（离屏）。

R4 新增：
- replace_selection / insert_after 成功时还原用户原有剪贴板（避免吞掉用户先前复制内容）
- 失败时保留新文本（供手动 Ctrl+V）
- is_target_elevated / is_current_elevated 在非 Windows 安全返回 False
- overlay._replace_fail_msg 区分「目标是管理员窗口」给具体指引

注意：本文件刻意不创建 QApplication —— 剪贴板函数全部 mock，且 `_replace_fail_msg`
不依赖 self 状态（可 unbound 调用）。这样避开离屏 Qt 在进程退出时的 teardown 崩溃
（与 test_ui_smoke 偶发 0xC0000005 同源），让 run_all 稳定通过。
运行： QT_QPA_PLATFORM=offscreen python tests/test_actions_clipboard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock  # noqa: E402

from promptpop import actions  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402


def _patch_windows(m, focus=True):
    """把 replace_selection/insert_after 里的 Windows 相关函数都接成可控桩。"""
    patches = [
        mock.patch.object(actions, "_is_valid_hwnd", return_value=True),
        mock.patch.object(actions, "_is_own_window", return_value=False),
        mock.patch.object(actions, "_force_foreground", return_value=True),
        mock.patch.object(actions, "_focus_still_on", return_value=focus),
        mock.patch.object(actions, "_send_ctrl_v"),
        mock.patch.object(actions, "_has_text_selection", return_value=False),
        mock.patch.object(actions, "time"),  # 去掉真实 sleep，加速
    ]
    for p in patches:
        p.start()
        m.append(p)


def test_replace_restores_old_on_success():
    calls = []
    m = []
    _patch_windows(m)
    with mock.patch.object(actions, "clipboard_get_text", return_value="OLD"), \
         mock.patch.object(actions, "clipboard_set_text", side_effect=lambda t: calls.append(t)):
        ok = actions.replace_selection("NEW", 123)
        assert ok is True
        # 先写新文本、成功后再还原旧文本
        assert calls == ["NEW", "OLD"]
    for p in reversed(m):
        p.stop()


def test_replace_keeps_new_on_failure():
    calls = []
    m = []
    _patch_windows(m, focus=False)
    with mock.patch.object(actions, "clipboard_get_text", return_value="OLD"), \
         mock.patch.object(actions, "clipboard_set_text", side_effect=lambda t: calls.append(t)):
        ok = actions.replace_selection("NEW", 123)
        assert ok is False
        # 失败：不还原，保留新文本供手动 Ctrl+V
        assert calls == ["NEW"]
    for p in reversed(m):
        p.stop()


def test_insert_restores_old_on_success():
    calls = []
    m = []
    _patch_windows(m)
    with mock.patch.object(actions, "clipboard_get_text", return_value="OLD2"), \
         mock.patch.object(actions, "clipboard_set_text", side_effect=lambda t: calls.append(t)):
        ok = actions.insert_after("NEW", 123)
        assert ok is True
        assert calls == ["NEW", "OLD2"]
    for p in reversed(m):
        p.stop()


def test_is_target_elevated_non_nt():
    with mock.patch.object(actions.os, "name", "posix"):
        assert actions.is_target_elevated(123) is False


def test_is_current_elevated_non_nt():
    with mock.patch.object(actions.os, "name", "posix"):
        assert actions.is_current_elevated() is False


def test_replace_fail_msg_elevated():
    # _replace_fail_msg 不依赖 self 状态，可 unbound 调用，避免构造 OverlayWindow
    with mock.patch.object(actions, "is_target_elevated", return_value=True), \
         mock.patch.object(actions, "is_current_elevated", return_value=False):
        msg = OverlayWindow._replace_fail_msg(None, 123)
        assert "管理员" in msg
        assert "手动 Ctrl+V" in msg


def test_replace_fail_msg_generic():
    with mock.patch.object(actions, "is_target_elevated", return_value=False):
        msg = OverlayWindow._replace_fail_msg(None, 123)
        assert "未能定位原窗口" in msg
        assert "管理员" not in msg


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
