"""历史「清空全部」功能测试（离屏）。

R6 新增：history.clear_history()（不可逆，返回删除条数）+ 库对话框「清空历史」按钮接线。
运行： QT_QPA_PLATFORM=offscreen python tests/test_history_clear.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_clear_")

from unittest import mock  # noqa: E402

from promptpop import history as H  # noqa: E402
from promptpop.config import Config  # noqa: E402
from promptpop.library_dialog import LibraryDialog  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def test_clear_history_empties():
    H.init_db()
    H.clear_history()  # 先净空
    for i in range(3):
        H.add_history("user", "deepseek", "m", "in%d" % i, "out%d" % i)
    assert len(H.list_history(200)) == 3
    n = H.clear_history()
    assert n == 3
    assert H.list_history(200) == []


def test_clear_history_empty_returns_zero():
    H.init_db()
    H.clear_history()
    assert H.clear_history() == 0


def test_dialog_clear_button_wired():
    _app()
    H.init_db()
    H.clear_history()
    H.add_history("user", "deepseek", "m", "x", "y")
    dlg = LibraryDialog(Config(), lambda: "")
    # 确认弹窗返回是、clear_history 真实执行
    with mock.patch.object(H, "clear_history", wraps=H.clear_history) as m_c, \
         mock.patch("promptpop.library_dialog.ui_util.exec_confirm", return_value=True):
        dlg._clear_history()
        m_c.assert_called_once()
    # 清空后界面列表应为空
    assert dlg._hist_all == []
    H.clear_history()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
