"""模板 {{var}} 变量填空回归测试（离屏）。

R1（v0.7.8）：util.render_template 此前无生产调用方——模板加载后 {{var}}
原样留在文本里（README 宣称的变量功能不可达）。本文件固化：加载含变量模板
时逐个询问并渲染；留空/取消保留占位符原样。
运行： QT_QPA_PLATFORM=offscreen python tests/test_template_vars.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_tplvar_")

from unittest import mock  # noqa: E402

from promptpop import history as H  # noqa: E402
from promptpop import ui_util  # noqa: E402
from promptpop.config import Config  # noqa: E402
from promptpop.library_dialog import LibraryDialog  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _dlg_with_template(content):
    _app()
    H.init_db()
    H.add_template("t", "自定义", content)
    dlg = LibraryDialog(Config(), lambda: "")
    dlg.tpl_list.setCurrentRow(0)
    return dlg


def test_load_template_fills_vars():
    dlg = _dlg_with_template("把 {{主题}} 写成 {{风格}} 风格")
    answers = {"主题": "爬虫", "风格": "教程"}
    emitted = []
    dlg.load_requested.connect(lambda i, o: emitted.append((i, o)))

    def fake_get_text(parent, title, label, default=""):
        for k, v in answers.items():
            if k in label:
                return (v, True)
        return ("", False)

    with mock.patch.object(ui_util, "get_text", side_effect=fake_get_text):
        dlg._load_template()
    assert emitted and emitted[0][1] == "把 爬虫 写成 教程 风格"
    H.clear_history()


def test_load_template_blank_keeps_placeholder():
    dlg = _dlg_with_template("把 {{主题}} 写成教程")
    emitted = []
    dlg.load_requested.connect(lambda i, o: emitted.append((i, o)))

    def fake_get_text(parent, title, label, default=""):
        return ("", True)     # 用户留空

    with mock.patch.object(ui_util, "get_text", side_effect=fake_get_text):
        dlg._load_template()
    assert emitted and emitted[0][1] == "把 {{主题}} 写成教程"   # 占位符保留
    H.clear_history()


def test_load_template_cancel_all_keeps_content():
    dlg = _dlg_with_template("把 {{主题}} 写成教程")
    emitted = []
    dlg.load_requested.connect(lambda i, o: emitted.append((i, o)))

    def fake_get_text(parent, title, label, default=""):
        return ("任意值", False)   # 每个变量都点取消

    with mock.patch.object(ui_util, "get_text", side_effect=fake_get_text):
        dlg._load_template()
    assert emitted and emitted[0][1] == "把 {{主题}} 写成教程"   # 原样加载
    H.clear_history()


def test_load_template_no_vars_no_prompt():
    dlg = _dlg_with_template("无变量模板正文")
    emitted = []
    dlg.load_requested.connect(lambda i, o: emitted.append((i, o)))
    with mock.patch.object(ui_util, "get_text") as m_get:
        dlg._load_template()
        m_get.assert_not_called()      # 无变量不打扰
    assert emitted and emitted[0][1] == "无变量模板正文"
    H.clear_history()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
