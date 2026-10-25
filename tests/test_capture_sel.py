"""取词主路径集成测试（离线可控）：验证光标降智真正接入 extract_selected_text。

覆盖 v0.7.6 R1 修复：此前 should_attempt_clipboard（光标降智）是死代码，
extract_selected_text 在 UIA 失败后无差别走剪贴板回退（Ctrl+C），导致非文本拖拽误弹工具条。
修复后：UIA 失败 → 看光标，非 I-beam/unknown 直接返回 none，不碰剪贴板。

运行： QT_QPA_PLATFORM=offscreen python tests/test_capture_sel.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

from promptpop import capture


def test_uia_hit_returns_without_clipboard():
    # UIA 取到文本 → 直接返回 uia，不调光标判定/剪贴板
    with mock.patch.object(capture, "extract_uia", return_value="  hello  "), \
         mock.patch.object(capture, "cursor_kind") as m_cur, \
         mock.patch.object(capture, "extract_clipboard") as m_cb:
        text, method = capture.extract_selected_text({}, "chrome.exe")
        assert text == "  hello  " and method == "uia"
        m_cur.assert_not_called()
        m_cb.assert_not_called()


def test_arrow_cursor_skips_clipboard():
    # UIA 失败 + 光标 arrow（非文本选择）→ 跳过剪贴板回退
    with mock.patch.object(capture, "extract_uia", return_value=""), \
         mock.patch.object(capture, "cursor_kind", return_value="arrow"), \
         mock.patch.object(capture, "extract_clipboard") as m_cb:
        text, method = capture.extract_selected_text({}, "chrome.exe")
        assert text == "" and method == "none"
        m_cb.assert_not_called()


def test_hand_cursor_skips_clipboard():
    with mock.patch.object(capture, "extract_uia", return_value=""), \
         mock.patch.object(capture, "cursor_kind", return_value="hand"), \
         mock.patch.object(capture, "extract_clipboard") as m_cb:
        text, method = capture.extract_selected_text({}, "chrome.exe")
        assert method == "none"
        m_cb.assert_not_called()


def test_ibeam_cursor_uses_clipboard():
    # UIA 失败 + 光标 ibeam（文本选择）→ 走剪贴板回退
    with mock.patch.object(capture, "extract_uia", return_value=""), \
         mock.patch.object(capture, "cursor_kind", return_value="ibeam"), \
         mock.patch.object(capture, "extract_clipboard", return_value="  选中文本  ") as m_cb:
        text, method = capture.extract_selected_text({}, "chrome.exe")
        assert text == "  选中文本  " and method == "clipboard"
        m_cb.assert_called_once()


def test_unknown_cursor_uses_clipboard():
    # 光标检测失败（unknown）保守走剪贴板，避免漏取
    with mock.patch.object(capture, "extract_uia", return_value=""), \
         mock.patch.object(capture, "cursor_kind", return_value="unknown"), \
         mock.patch.object(capture, "extract_clipboard", return_value="x") as m_cb:
        text, method = capture.extract_selected_text({}, "chrome.exe")
        assert method == "clipboard"
        m_cb.assert_called_once()


def test_custom_cursor_program_in_list_uses_clipboard():
    # 自定义光标程序（Acrobat）在排除名单内 → 强制走剪贴板
    with mock.patch.object(capture, "extract_uia", return_value=""), \
         mock.patch.object(capture, "cursor_kind", return_value="custom"), \
         mock.patch.object(capture, "extract_clipboard", return_value="pdf text") as m_cb:
        text, method = capture.extract_selected_text(
            {"exclude_cursor_detect": ["acrobat.exe"]}, "acrobat.exe")
        assert method == "clipboard"
        m_cb.assert_called_once()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
