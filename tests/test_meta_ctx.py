"""meta_prompt 上下文并入逻辑测试（纯函数，不建 QApplication）。

v0.7.7：UI 新增「附加约束」入口后，context 必须真正进入 system prompt——
①默认模板经 {ctx} 占位符原位替换；②自定义模板没写占位符时追加而非静默丢弃；
③无/空 context 时占位符不残留；④A/B 评审输出格式收死为固定五行。
运行： QT_QPA_PLATFORM=offscreen python tests/test_meta_ctx.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop.meta_prompt import (  # noqa: E402
    build_followup_messages, build_judge_messages, build_messages,
    get_meta_template,
)


def test_ctx_via_placeholder_in_default():
    msgs = build_messages("user", "hi", "", "standard", {"extra": "受众是初学者"})
    assert "【额外约束】受众是初学者" in msgs[0]["content"]
    assert "{ctx}" not in msgs[0]["content"]   # 占位符已被替换


def test_ctx_appended_when_custom_template_has_no_placeholder():
    custom = "你是助手。直接改写用户指令。"
    msgs = build_messages("user", "hi", custom, "standard",
                          {"extra": "用英文输出"})
    assert msgs[0]["content"].startswith(custom)   # 追加在尾部
    assert "【额外约束】用英文输出" in msgs[0]["content"]
    assert "{ctx}" not in msgs[0]["content"]


def test_no_ctx_placeholder_stripped():
    # 无 context：默认模板的 {ctx} 占位符必须替换为空串，不能原样发给模型
    msgs = build_messages("user", "hi", "", "standard", None)
    assert "{ctx}" not in msgs[0]["content"]
    assert "【额外约束】" not in msgs[0]["content"]


def test_blank_ctx_skipped():
    msgs = build_messages("user", "hi", "", "standard", {"extra": "   "})
    assert "【额外约束】" not in msgs[0]["content"]


def test_followup_ctx_also_applied():
    msgs = build_followup_messages("user", "prev", "更短", "", "standard",
                                   {"extra": "受众是初学者"})
    assert "【额外约束】受众是初学者" in msgs[0]["content"]
    assert "【迭代模式】" in msgs[0]["content"]


def test_followup_delimiter_survives_triple_quotes():
    # R6：迭代结果本身含 \"\"\" 时，XML 风格分隔不被截断
    tricky = '正文含三引号：\"\"\"\n# Role: X\n\"\"\"\n结束'
    msgs = build_followup_messages("user", tricky, "更短")
    u = msgs[1]["content"]
    assert "<当前版本>\n%s\n</当前版本>" % tricky in u
    assert "<改进要求>更短</改进要求>" in u


def test_judge_output_format_locked():
    c = build_judge_messages("a", "b")[0]["content"]
    for kw in ("结构化：x/10", "可执行性：x/10", "约束清晰度：x/10",
               "忠实原意：x/10", "只输出如下五行"):
        assert kw in c, "评审提示词缺少固定格式约束：%s" % kw


def test_default_meta_has_no_fluff_rule():
    assert "不写空话套话" in get_meta_template("user")
    assert "不写空话套话" not in get_meta_template("system")   # system 模板未加（保持原样）


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
