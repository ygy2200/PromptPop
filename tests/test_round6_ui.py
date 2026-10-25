"""第六轮 R12-R19 改进回归测试（离屏）。

R12 取词重入防御 / R14 清除已存 Key / R16 导出 MD 围栏 / R17 端点编辑 / R19 基本 tab 滚动。
运行： QT_QPA_PLATFORM=offscreen python tests/test_round6_ui.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_r6_")

from unittest import mock  # noqa: E402

from promptpop import capture  # noqa: E402
from promptpop import history as H  # noqa: E402
from promptpop import secrets  # noqa: E402
from promptpop import settings_dialog as SD  # noqa: E402
from promptpop.config import Config  # noqa: E402
from promptpop.settings_dialog import SettingsDialog, _CustomProviderDialog  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


from PySide6.QtWidgets import QApplication  # noqa: E402


# ---------- R12：取词重入防御 ----------
def test_extract_selected_text_reentrancy_guard():
    _app()
    capture._EXTRACTING = True
    try:
        with mock.patch.object(capture, "extract_uia") as m_uia:
            text, method = capture.extract_selected_text({}, "")
            m_uia.assert_not_called()        # 重入直接短路
        assert (text, method) == ("", "none")
    finally:
        capture._EXTRACTING = False
    # 非重入路径正常走（uia mock 返回文本）
    with mock.patch.object(capture, "extract_uia", return_value="选中"):
        text, method = capture.extract_selected_text({}, "")
    assert (text, method) == ("选中", "uia")


# ---------- R14：清除已存 Key ----------
def test_clear_saved_key_button():
    _app()
    dlg = SettingsDialog(Config())
    clears = [b for b in dlg.findChildren(QPushButton) if b.text() == "清除"]
    assert len(clears) == 2                     # DeepSeek / OpenAI 各一
    with mock.patch.object(SD.secrets, "set_key", return_value=True) as m_set, \
         mock.patch.object(SD.ui_util, "exec_confirm", return_value=True):
        clears[0].click()
        m_set.assert_called_once_with("deepseek", "")
    assert "已清除" in dlg.key_deepseek.placeholderText()
    assert "deepseek" in dlg._key_cleared


def test_clear_saved_key_cancel_keeps():
    _app()
    dlg = SettingsDialog(Config())
    clears = [b for b in dlg.findChildren(QPushButton) if b.text() == "清除"]
    with mock.patch.object(SD.secrets, "set_key") as m_set, \
         mock.patch.object(SD.ui_util, "exec_confirm", return_value=False):
        clears[1].click()
        m_set.assert_not_called()
    assert "openai" not in dlg._key_cleared


# ---------- R16：导出 Markdown 围栏冲突 ----------
def test_export_markdown_fence_switch():
    H.init_db()
    H.clear_history()
    rows = [(1, 1700000000, "user", "p", "m", "普通输入", "输出含 ```代码", "")]
    md = H.export_markdown(rows)
    assert "~~~~" in md                       # 内容含 ``` → 换波浪线围栏
    assert not any(l.startswith("```") for l in md.splitlines())   # 无反引号围栏行
    rows2 = [(1, 1700000000, "user", "p", "m", "普通", "普通输出", "")]
    md2 = H.export_markdown(rows2)
    assert "```" in md2 and "~~~~" not in md2
    H.clear_history()


# ---------- R17：自定义端点编辑 ----------
def test_edit_endpoint_prefill_and_update():
    _app()
    cfg = Config({"custom_providers": [
        {"id": "MyEP", "label": "MyEP", "base_url": "https://old.example/v1",
         "default_model": "old-model", "needs_key": True, "api_key": "sk-old"}]})
    dlg = SettingsDialog(cfg)
    dlg.custom_list.setCurrentRow(0)
    # 预填验证
    pre = _CustomProviderDialog(initial={"id": "MyEP", "label": "MyEP",
                                         "base_url": "https://old.example/v1",
                                         "default_model": "old-model",
                                         "needs_key": True, "api_key": "sk-old"})
    assert pre.name.text() == "MyEP"
    assert pre.base_url.text() == "https://old.example/v1"
    assert "已保存" in pre.key.placeholderText()

    # 编辑流程：exec_dialog 里改控件 → to_entry 读出 → 同 id 更新
    def fake_exec(d):
        d.name.setText("MyEP")
        d.base_url.setText("https://new.example/v1")
        d.model.setText("new-model")
        return True

    with mock.patch.object(SD.ui_util, "exec_dialog", side_effect=fake_exec):
        dlg._on_edit_endpoint()
    eps = cfg.data["custom_providers"]
    assert len(eps) == 1 and eps[0]["base_url"] == "https://new.example/v1"
    assert eps[0]["default_model"] == "new-model"
    assert eps[0]["api_key"] == "sk-old"      # Key 留空 = 保留原 Key


def test_edit_endpoint_no_selection_noop():
    _app()
    cfg = Config()
    dlg = SettingsDialog(cfg)
    dlg._on_edit_endpoint()                    # 无选中：静默返回不崩


# ---------- R19：基本 tab 滚动 ----------
def test_basic_tab_is_scrollable():
    from PySide6.QtWidgets import QScrollArea
    _app()
    dlg = SettingsDialog(Config())
    tab = dlg.findChildren(QScrollArea)
    assert tab, "基本 tab 应包裹在 QScrollArea 中（小屏适配）"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
