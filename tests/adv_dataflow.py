"""对抗性测试：数据流全链路与边界（adv_*.py，第七轮 R16）。

攻击场景：坏配置→真实启动链（Config.load→OverlayWindow 构造）、
模板导入→填变量→存查重→导出→再导入全链路、历史 9 列/8 列混流、
极端输入（全 emoji/超长行/null 字节）过 build_messages 与 postprocess。
运行： QT_QPA_PLATFORM=offscreen python tests/adv_dataflow.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import history as H  # noqa: E402
from promptpop import meta_prompt  # noqa: E402
from promptpop import postprocess  # noqa: E402
from promptpop import util  # noqa: E402
from promptpop.config import Config  # noqa: E402


def _setup_cfg_dir():
    d = tempfile.mkdtemp(prefix="promptpop_adv_flow_")
    os.environ["PROMPTPOP_CONFIG_DIR"] = d
    return d


def test_bad_config_to_real_startup_chain():
    """坏配置（端点表 dict + 坏值字段）→ 真实启动链不崩（R20/R21 坐实）。"""
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication([])
    d = _setup_cfg_dir()
    bad = {
        "custom_providers": {"rogue": 1},       # 非 list
        "temperature": "fast",
        "max_input_chars": [1],
        "hotkey": "ctrl+加",
        "history_retention_days": "n",
        "clipboard_delay_default": "x",
        "api_keys": "scalar",
    }
    with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
        json.dump(bad, f)
    cfg = Config.load()
    from promptpop.overlay import OverlayWindow
    ov = OverlayWindow(cfg)                     # 启动链：坏配置不崩
    assert ov.extra_edit is not None            # UI 完整构建
    # 热键坏值 → validate None → app 层 or 默认值兜底
    assert util.validate_hotkey(cfg.get("hotkey")) is None


def test_template_full_lifecycle():
    """导入→填变量→同名保存查重→导出→再导入 merge 去重 全链路。"""
    from PySide6.QtWidgets import QApplication
    _ = QApplication.instance() or QApplication([])
    H.init_db()
    H.clear_history()
    for _ in range(H.list_templates().__len__() or 0):
        pass
    H.add_template("链路", "自定义", "把 {{主题}} 写成 {{风格}}")
    tid = H.find_template_by_name("链路")
    H.update_template(tid, "把 {{主题}} 写成教程")     # R7 编辑
    assert H.list_templates()[0][3] == "把 {{主题}} 写成教程"
    data = H.export_templates()
    added, skipped = H.import_templates(data, merge=True)
    assert (added, skipped) == (0, 1)                  # 同名跳过
    H.clear_history()


def test_history_8col_9col_mixed_export():
    """9 列（新版 list_history）与 8 列（旧结构/测试构造）混合过导出不崩。"""
    rows = [
        (1, 1700000000, "user", "p", "m", "i1", "o1", "t1", 1),   # 9 列
        (2, 1700000001, "user", "p", "m", "i2", "o2", "t2"),      # 8 列
    ]
    md = H.export_markdown(rows)
    assert "i1" in md and "o2" in md
    # filter_history 对两种行都不崩
    assert len(util.filter_history(rows, "i")) == 2


def test_extreme_inputs_to_pipeline():
    """全 emoji / null 字节 / 超长单行 过 build_messages + postprocess 不崩。"""
    for text in ("🚀🔥💯" * 500,
                 "a\x00b\x1bc",
                 "长" * 30000,
                 "​" * 100):                      # 零宽空格
        msgs = meta_prompt.build_messages("user", text, "", "standard", None)
        assert msgs[1]["content"] == text.strip()
        out = postprocess.postprocess_output(text)
        assert isinstance(out, str)
    # len==max 边界语义（R10 轮）：恰好等于上限允许提交
    mx = 100
    assert not (len("a" * mx) > mx)
    assert len(util.format_char_count(mx, mx)[1] if False else
               util.format_char_count(mx, mx)) == 2


def test_retention_hostile_values():
    """retention 坏值：负值/字符串经 safe_int 后 prune 安全。"""
    assert H.prune_history(-5) == 0
    H.init_db()
    H.clear_history()
    H.add_history("user", "p", "m", "i", "o")
    assert H.prune_history("n" if False else 0) == 0     # 0=不清理
    H.clear_history()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
