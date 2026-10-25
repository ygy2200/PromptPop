"""对抗性测试：文本处理层 postprocess + local_actions（adv_*.py）。

攻击场景：恶意代码围栏、嵌套/未闭合围栏、null 字节、纯标点、CRLF 混合、
万级行列表、深度嵌套 JSON、1MB 大文本性能。
运行： QT_QPA_PLATFORM=offscreen python tests/adv_text.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import local_actions as LA  # noqa: E402
from promptpop import postprocess as PP  # noqa: E402


def test_strip_fences_hostile():
    # 四反引号/嵌套等罕见边缘：只要求不崩、返回 str（具体剥除行为不承诺）
    for hostile in ("````\nx\n````", "```py\n```py\nx\n```\n```",
                    "```\n不闭合", "```", "~~~~", "```\r\nx\r\n```"):
        assert isinstance(PP.strip_fences(hostile), str), hostile
    assert PP.strip_fences("") == ""
    assert PP.strip_fences(None) == ""
    # 正常路径不回归
    assert PP.strip_fences("```python\nprint(1)\n```") == "print(1)"
    assert PP.strip_fences("~~~\nx\n~~~") == "x"


def test_prefix_strip_hostile():
    assert PP.strip_leading_prefixes("Sure! Here's the thing") == "thing"
    assert PP.strip_leading_prefixes("OK, okay, 好") == "好" or \
        PP.strip_leading_prefixes("OK, okay, 好").startswith("好")
    assert PP.strip_leading_prefixes("这是中文正文") == "这是中文正文"  # 中文不误伤
    assert PP.postprocess_output("# Role: X\n正文") == "# Role: X\n正文"


def test_local_actions_hostile_inputs():
    for fn in (LA.clean_ws, LA.to_bullets, LA.to_numbered, LA.pretty_json,
               LA.dedupe_lines, LA.extract_urls, LA.to_english_punct,
               LA.remove_blank_lines, LA.strip_urls, LA.strip_code_fence,
               LA.apply if False else LA.clean_ws):
        assert fn("") is not None
        assert fn(None) is not None            # None 不崩
        assert fn("\x00\x01\x02") is not None  # 控制字符不崩
    assert LA.apply("no-such-action", "x") == "x"          # 未知动作原文返回
    assert LA.apply("no-such-action", None) == ""


def test_to_numbered_tenthousand_lines():
    text = "\n".join("行%d" % i for i in range(10000))
    t0 = time.time()
    out = LA.to_numbered(text)
    assert time.time() - t0 < 3.0
    assert out.splitlines()[-1] == "10000. 行9999"


def test_pretty_json_deep_nesting():
    deep = "[" * 500 + "]" * 500           # 500 层嵌套（json 递归限制内）
    out = LA.pretty_json(deep)
    assert isinstance(out, str)            # 合法但不崩；超限则原文返回
    assert LA.pretty_json("{bad json") == "{bad json"
    assert LA.pretty_json("null") == "null"


def test_extract_urls_hostile():
    assert LA.extract_urls("见 https://a.b/c）与 http://x.y?q=1。") == \
        "https://a.b/c\nhttp://x.y?q=1"
    assert LA.extract_urls("无链接") == ""
    assert LA.extract_urls(None) == ""
    # 巨长 URL 截尾标点剥除不崩
    assert LA.extract_urls("https://" + "a" * 5000 + "。").startswith("https://")


def test_strip_urls_and_ws_hostile():
    assert LA.strip_urls("https://a.com") == ""          # 只含 URL
    assert LA.strip_urls(None) == ""
    assert LA.clean_ws("\r\n\r\n\r\n\r\n") == ""
    assert LA.clean_ws("a\r\n\r\r\nb") .count("\n\n") <= 1  # 3+连空行压缩


def test_dedupe_and_bullets_hostile():
    assert LA.dedupe_lines("a\na\n a \na") == "a"    # strip 后同 key 全去重
    assert LA.dedupe_lines("") == ""
    assert LA.to_bullets("\n\n\n") == ""             # 全空行被 clean_ws 压掉
    assert LA.to_bullets("- x") == "- x"             # 已是列表不重复加
    assert LA.to_english_punct("“引号”‘单’（括）") == "\"引号\"'单'(括)"


def test_1mb_performance():
    big = ("这是一段中文正文，包含标点。 \n" * 30000)[:1_000_000]
    t0 = time.time()
    for fn in (LA.clean_ws, LA.to_bullets, LA.dedupe_lines, LA.to_english_punct):
        fn(big)
    assert time.time() - t0 < 5.0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
