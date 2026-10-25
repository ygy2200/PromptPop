"""库对话框「打标签」回归测试（离屏）。

v0.7.7 修复：_tag_history 调 ui_util.get_text 时误传 text= 关键字（实参名是
default），一按「打标签」即 TypeError，历史标签功能自引入起完全不可用且
无测试覆盖。本文件固化该回归：传参必须是 default=，且打标签真实生效。
运行： QT_QPA_PLATFORM=offscreen python tests/test_library_tag.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_tag_")

from unittest import mock  # noqa: E402

from promptpop import history as H  # noqa: E402
from promptpop import ui_util  # noqa: E402
from promptpop.config import Config  # noqa: E402
from promptpop.library_dialog import LibraryDialog  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _dlg_with_one_row():
    _app()
    H.init_db()
    H.clear_history()
    H.add_history("user", "deepseek", "m", "hello world", "out")
    dlg = LibraryDialog(Config(), lambda: "")
    dlg.hist_list.setCurrentRow(0)
    return dlg


def test_tag_history_get_text_kwargs():
    """回归核心：get_text 必须以 default= 传当前标签（text= 是 TypeError）。"""
    dlg = _dlg_with_one_row()
    seen = {}

    def fake_get_text(parent, title, label, default=""):
        seen["default"] = default
        return ("tag1,tag2", True)

    with mock.patch.object(ui_util, "get_text", side_effect=fake_get_text), \
         mock.patch.object(H, "set_tags", wraps=H.set_tags) as m_set:
        dlg._tag_history()
        m_set.assert_called_once()
    assert seen["default"] == ""            # 原标签为空，经 default 传入
    rows = H.list_history(200)
    assert rows and rows[0][7] == "tag1,tag2"   # 标签真实写库
    H.clear_history()


def test_tag_history_prefills_existing_tags():
    """已有标签应回填到输入框（默认值可见，用户增量编辑而非清空重写）。"""
    dlg = _dlg_with_one_row()
    H.set_tags(dlg._hist_ids[0], ["old"])
    dlg._refresh_history()
    dlg.hist_list.setCurrentRow(0)
    seen = {}

    def fake_get_text(parent, title, label, default=""):
        seen["default"] = default
        return ("old,new", True)

    with mock.patch.object(ui_util, "get_text", side_effect=fake_get_text):
        dlg._tag_history()
    assert seen["default"] == "old"
    assert H.list_history(200)[0][7] == "old,new"
    H.clear_history()


def test_tag_history_cancel_keeps_tags():
    dlg = _dlg_with_one_row()

    def fake_get_text(parent, title, label, default=""):
        return ("whatever", False)          # 用户点取消

    with mock.patch.object(ui_util, "get_text", side_effect=fake_get_text), \
         mock.patch.object(H, "set_tags") as m_set:
        dlg._tag_history()
        m_set.assert_not_called()
    H.clear_history()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
