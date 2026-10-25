"""第七轮 R1-R4 改进回归测试（离屏）。

R1 固定历史（pin_history 死功能接通）/ R2 打开配置目录 / R3 托盘关于 / R4 设置重复打开守卫。
运行： QT_QPA_PLATFORM=offscreen python tests/test_round7_ui.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_r7_")

from unittest import mock  # noqa: E402

from promptpop import app as A  # noqa: E402
from promptpop import history as H  # noqa: E402
from promptpop import settings_dialog as SD  # noqa: E402
from promptpop import ui_util  # noqa: E402
from promptpop.config import Config  # noqa: E402
from promptpop.library_dialog import LibraryDialog  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


# ---------- R1：固定历史 ----------
def test_toggle_pin_roundtrip():
    _app()
    H.init_db()
    H.clear_history()
    H.add_history("user", "p", "m", "要固定的记录", "out")
    dlg = LibraryDialog(Config(), lambda: "")
    dlg.hist_list.setCurrentRow(0)
    assert "📌" not in dlg.hist_list.item(0).text()
    dlg._toggle_pin()
    assert "📌" in dlg.hist_list.item(0).text()       # 列表标记
    assert H.list_history(10)[0][8] == 1              # 落库
    dlg.hist_list.setCurrentRow(0)
    dlg._toggle_pin()
    assert "📌" not in dlg.hist_list.item(0).text()
    assert H.list_history(10)[0][8] == 0
    H.clear_history()


def test_toggle_pin_no_selection():
    _app()
    dlg = LibraryDialog(Config(), lambda: "")
    with mock.patch.object(ui_util, "exec_message") as m_msg:
        dlg._toggle_pin()
        m_msg.assert_called_once()


def test_pinned_survives_export_markdown_9col():
    rows = [(1, 1700000000, "user", "p", "m", "in", "out", "t", 1)]   # 9 列新结构
    md = H.export_markdown(rows)                                       # 不崩即可
    assert "PromptPop 历史导出" in md


# ---------- R2：打开配置目录 ----------
def test_open_config_dir_button():
    _app()
    dlg = SD.SettingsDialog(Config())
    btns = [b for b in dlg.findChildren(type(dlg)) if False]  # 占位防误用
    found = [b for b in dlg.findChildren(__import__(
        "PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
        if b.text() == "打开配置目录…"]
    assert len(found) == 1
    import os as _os
    with mock.patch.object(_os, "startfile") as m_open:
        found[0].click()
        m_open.assert_called_once()               # Windows 路径真实调用


# ---------- R3：托盘关于 ----------
def test_show_about_version():
    _app()
    from promptpop import __version__
    with mock.patch.object(ui_util, "exec_message") as m_msg:
        A._show_about()
        m_msg.assert_called_once()
        args = m_msg.call_args[0]
        assert args[1] == "关于 PromptPop"
        assert __version__ in args[2] and "config" not in args[2].split("\n")[1]


# ---------- R4：设置重复打开守卫 ----------
def test_settings_reopen_guard():
    _app()
    cfg = Config()
    ov = OverlayWindow(cfg)
    opener = A.build_settings_opener(cfg, ov, None)
    fake = QDialog()
    fake.setWindowTitle("PromptPop 设置")
    fake.show()
    ov._active_dialog = fake
    with mock.patch.object(SD, "SettingsDialog") as m_cls, \
         mock.patch.object(ui_util, "exec_dialog") as m_exec:
        opener()
        m_cls.assert_not_called()                 # 已开着：只提前，不叠开
        m_exec.assert_not_called()
    ov._active_dialog = None


def test_settings_open_normal_when_none_active():
    _app()
    cfg = Config()
    ov = OverlayWindow(cfg)
    opener = A.build_settings_opener(cfg, ov, None)
    with mock.patch.object(ui_util, "exec_dialog", return_value=False) as m_exec:
        opener()
        m_exec.assert_called_once()               # 无活动弹窗：正常打开


# ---------- R8：busy 时加载库/本地整理拦截 ----------
def test_library_load_blocked_while_busy():
    _app()
    ov = OverlayWindow(Config())
    ov.worker = mock.MagicMock()
    ov.worker.isRunning.return_value = True
    ov.result_box.setPlainText("流式中的内容")
    with mock.patch.object(ov, "_status") as m_st:
        ov._on_library_load("库输入", "库输出")
        m_st.assert_called_once()
    assert ov.result_box.toPlainText() == "流式中的内容"   # 未被覆盖


def test_local_tools_blocked_while_busy():
    _app()
    ov = OverlayWindow(Config())
    ov.worker = mock.MagicMock()
    ov.worker.isRunning.return_value = True
    with mock.patch.object(ov, "_status") as m_st:
        ov._on_local_tools()
        m_st.assert_called_once()                 # busy 时面板不打开


def test_library_load_normal_when_idle():
    _app()
    ov = OverlayWindow(Config())
    ov.worker = None
    ov._on_library_load("输入内容", "输出内容")   # 空闲时正常加载
    assert ov.result_box.toPlainText() == "输出内容"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
