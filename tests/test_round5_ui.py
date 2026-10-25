"""第五轮 R3/R4 UI 改进回归测试（离屏）。

R3：历史列表/导出上限 200→1000，触顶时窗口标题明示「仅显示最近 1000 条」。
R4：设置「优化模板」tab 新增「载入默认模板」按钮（空框直接载入、有内容先确认）。
运行： QT_QPA_PLATFORM=offscreen python tests/test_round5_ui.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_r5_")

from unittest import mock  # noqa: E402

from promptpop import history as H  # noqa: E402
from promptpop import ui_util  # noqa: E402
from promptpop.config import Config  # noqa: E402
from promptpop.library_dialog import LibraryDialog  # noqa: E402
from promptpop.settings_dialog import SettingsDialog  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


# ---------- R3：历史上限提示 ----------
def _fake_rows(n):
    return [(i, 1700000000.0 + i, "user", "deepseek", "m", "in%d" % i, "out", "")
            for i in range(n)]


def test_history_cap_hint_when_full():
    _app()
    dlg = LibraryDialog(Config(), lambda: "")
    with mock.patch("promptpop.library_dialog.history.list_history",
                    return_value=_fake_rows(1000)):
        dlg._refresh_history()
    assert "仅显示最近 1000 条" in dlg.windowTitle()


def test_history_no_hint_below_cap():
    _app()
    dlg = LibraryDialog(Config(), lambda: "")
    with mock.patch("promptpop.library_dialog.history.list_history",
                    return_value=_fake_rows(5)):
        dlg._refresh_history()
    assert "仅显示最近" not in dlg.windowTitle()


# ---------- R4：载入默认模板 ----------
def test_load_default_meta_into_empty_no_confirm():
    _app()
    dlg = SettingsDialog(Config())
    dlg.meta_user.setPlainText("")
    with mock.patch.object(ui_util, "exec_confirm") as m_c:
        dlg._load_default_meta(dlg.meta_user, "user")
        m_c.assert_not_called()          # 空框不烦人
    assert "不写空话套话" in dlg.meta_user.toPlainText()   # 默认模板特征句


def test_load_default_meta_overwrite_needs_confirm():
    _app()
    dlg = SettingsDialog(Config())
    dlg.meta_system.setPlainText("我的自定义模板")
    with mock.patch.object(ui_util, "exec_confirm", return_value=False) as m_c:
        dlg._load_default_meta(dlg.meta_system, "system")
        m_c.assert_called_once()
    assert dlg.meta_system.toPlainText() == "我的自定义模板"   # 拒绝则不动

    with mock.patch.object(ui_util, "exec_confirm", return_value=True):
        dlg._load_default_meta(dlg.meta_system, "system")
    assert "# Role:" in dlg.meta_system.toPlainText()        # 确认后覆盖为默认


# ---------- R7：模板编辑 ----------
def test_update_template_db():
    _app()
    H.init_db()
    H.add_template("ed", "自定义", "旧内容")
    tid = H.list_templates()[0][0]
    assert H.update_template(tid, "新内容") is True
    assert H.list_templates()[0][3] == "新内容"      # (id, name, category, content)
    assert H.update_template(99999, "不存在") is False
    H.clear_history()


def test_edit_template_dialog_wired():
    _app()
    H.init_db()
    H.clear_history()
    H.add_template("ed2", "自定义", "旧内容")
    dlg = LibraryDialog(Config(), lambda: "")
    dlg.tpl_list.setCurrentRow(0)

    def fake_exec(d):
        from PySide6.QtWidgets import QPlainTextEdit
        d.findChild(QPlainTextEdit).setPlainText("改好的内容")
        return True

    with mock.patch("promptpop.library_dialog.ui_util.exec_dialog",
                    side_effect=fake_exec):
        dlg._edit_template()
    assert H.list_templates()[0][3] == "改好的内容"
    H.clear_history()


def test_edit_template_cancel_keeps():
    _app()
    H.init_db()
    H.clear_history()
    H.add_template("ed3", "自定义", "保留我")
    dlg = LibraryDialog(Config(), lambda: "")
    dlg.tpl_list.setCurrentRow(0)
    with mock.patch("promptpop.library_dialog.ui_util.exec_dialog",
                    return_value=False):
        dlg._edit_template()
    assert H.list_templates()[0][3] == "保留我"
    H.clear_history()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
