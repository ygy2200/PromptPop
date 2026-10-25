"""设置面板「备份与迁移」tab 测试（离屏）：验证导出/导入按钮接线与配置调用。

覆盖 R3 新增的 config 导出/导入 UI 入口（此前 config.py 已实现 import_from/export_to
但设置面板无入口）。
运行： QT_QPA_PLATFORM=offscreen python tests/test_settings_backup.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from promptpop.config import Config  # noqa: E402
from promptpop import settings_dialog, ui_util  # noqa: E402
from promptpop.settings_dialog import SettingsDialog  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def test_backup_export(tmp_path):
    _app()
    dlg = SettingsDialog(Config())
    p = str(tmp_path / "c.json")
    with mock.patch.object(settings_dialog.QFileDialog, "getSaveFileName",
                           return_value=(p, "")), \
         mock.patch.object(dlg.config, "export_to") as m_e, \
         mock.patch.object(ui_util, "exec_message"):
        dlg._on_export_config()
        m_e.assert_called_once_with(p)


def test_backup_import(tmp_path):
    _app()
    dlg = SettingsDialog(Config())
    p = str(tmp_path / "c.json")
    with mock.patch.object(settings_dialog.QFileDialog, "getOpenFileName",
                           return_value=(p, "")), \
         mock.patch.object(ui_util, "exec_confirm", return_value=True), \
         mock.patch.object(dlg.config, "import_from") as m_i, \
         mock.patch.object(ui_util, "exec_message"):
        dlg._on_import_config()
        m_i.assert_called_once_with(p)


def test_backup_import_cancel_no_call(tmp_path):
    _app()
    dlg = SettingsDialog(Config())
    p = str(tmp_path / "c.json")
    with mock.patch.object(settings_dialog.QFileDialog, "getOpenFileName",
                           return_value=(p, "")), \
         mock.patch.object(ui_util, "exec_confirm", return_value=False), \
         mock.patch.object(dlg.config, "import_from") as m_i:
        dlg._on_import_config()
        m_i.assert_not_called()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
