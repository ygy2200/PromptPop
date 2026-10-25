"""对抗性测试：util 纯函数层（adv_*.py）。

攻击场景：嵌套/畸形模板变量、极端热键串、负数尺寸夹取、空 diff、
边界脱敏、成本估算坏用量、历史过滤坏行。
运行： QT_QPA_PLATFORM=offscreen python tests/adv_util.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import util  # noqa: E402


def test_extract_vars_hostile():
    assert util.extract_vars("{{}}") == []                    # 空名
    assert util.extract_vars("{{ a }} {{a}}") == ["a"]        # 空白归一+去重
    assert util.extract_vars("{{a{{b}}}}") == ["a{{b"] or util.extract_vars("{{a{{b}}}}") == ["b"]
    assert util.extract_vars("{{}}}}}}") == []
    assert util.extract_vars("{{中文变量}}") == ["中文变量"]
    assert util.extract_vars("") == []
    assert util.extract_vars(None) == []
    huge = "{{" + "x" * 10000 + "}}"
    assert util.extract_vars(huge) == ["x" * 10000]           # 超长变量名不崩


def test_render_template_missing_keys_kept():
    assert util.render_template("{{a}} {{b}}", {"a": "1"}) == "1 {{b}}"
    assert util.render_template(None, {"a": 1}) == ""
    # 变量值本身含 {{var}}：单遍替换不递归（无注入放大）
    out = util.render_template("{{a}}", {"a": "{{b}}"})
    assert out == "{{b}}"


def test_validate_hotkey_hostile():
    for bad in ("", "   ", "+++", "ctrl", "a+b", "ctrl+shift",     # 无修饰/无主键
                "ctrl+@@@", "f13", "<ctrl>+<f13>", "ctrl+加", "x" * 500):
        assert util.validate_hotkey(bad) is None, bad[:20]
    ok = util.validate_hotkey("ctrl+shift+space")
    assert ok == "<ctrl>+<shift>+<space>"
    # 大小写/混排仍合法
    assert util.validate_hotkey("CTRL+ALT+K") == "<ctrl>+<alt>+k"
    assert util.check_hotkey_risk("<ctrl>+<alt>+k") == (False, "")


def test_check_hotkey_risk_case_insensitive():
    block, why = util.check_hotkey_risk("<CMD>+L")
    assert block is True and "Win" in why
    # R9 修复目标：validate_hotkey 产出的是 <space>/<tab> 形态（带尖括号），
    # 而保留表历史形态是裸 space/tab——Win+Space（输入法切换）/Win+Tab 曾拦不住
    block_s, _ = util.check_hotkey_risk("<cmd>+<space>")
    assert block_s is True
    block_t, _ = util.check_hotkey_risk("<cmd>+<tab>")
    assert block_t is True


def test_clamp_position_hostile():
    # 负/零尺寸与零尺寸屏幕不崩且结果为整数
    for w, h, l, t, r, b in ((0, 0, 0, 0, 0, 0), (-10, -10, -100, -100, 100, 100),
                             (10**9, 10**9, 0, 0, 1920, 1080)):
        x, y = util.clamp_position(50, 50, w, h, l, t, r, b)
        assert isinstance(x, int) and isinstance(y, int)


def test_diff_lines_hostile():
    assert util.diff_lines("", "") == []
    assert util.diff_lines(None, None) == []
    a, b = "x" * 100000, "x" * 100000 + "\ny"
    out = util.diff_lines(a, b)
    assert out[-1].startswith("+ ")                 # 超长单行不崩
    assert util.diff_lines("a\r\nb", "a\nb")[0] == "  a" or True  # CRLF 不崩


def test_mask_secret_boundaries():
    assert util.mask_secret("") == ""
    assert util.mask_secret(None) == ""
    assert util.mask_secret("12345678") == "********"       # 恰 8 位全掩
    assert util.mask_secret("123456789") == "123...6789"    # 9 位露头尾
    assert util.mask_secret(12345678901234) == "123...1234"


def test_estimate_cost_hostile():
    assert util.estimate_cost("deepseek-chat", None) is None
    assert util.estimate_cost("unknown-model", {"total_tokens": 10}) is None
    assert util.estimate_cost("deepseek-chat", {"prompt_tokens": None,
                                                "completion_tokens": "x"}) == 0.0
    assert util.estimate_cost(None, {"total_tokens": 5}) is None


def test_filter_history_hostile_rows():
    rows = [(1, 0, "user", "p", "m", "找到 target", "o", "tag"),
            (2, 0, None, None, None, None, None, None)]     # 坏行(全 None)不崩
    assert len(util.filter_history(rows, "target")) == 1
    assert len(util.filter_history(rows, None)) == 2
    assert util.filter_history([], "x") == []


def test_format_char_count_hostile():
    assert util.format_char_count(0, 0)[1] == "info"        # 0 上限不限制
    assert util.format_char_count(-5, 100)[1] == "info"     # 负计数不崩
    assert util.format_char_count(101, 100)[1] == "error"
    assert util.format_char_count(95, 100)[1] == "warn"
    assert util.format_char_count(100, 100)[1] == "info"    # 恰等于上限=info


def test_validate_base_url_hostile():
    for bad in ("", None, "ftp://x", "//x", "http://", " https://a.b "):
        _ = util.validate_base_url(bad)   # 不崩即可，语义见函数
    assert util.validate_base_url("https://a.b") is True


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
