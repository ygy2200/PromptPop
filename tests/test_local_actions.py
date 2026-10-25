"""本地文本动作（无需 API Key / 不联网 / 零成本）纯函数测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import local_actions as L  # noqa: E402


def main():
    # 清理空白：行尾空白 + 3+ 连续空行压缩 + 首尾空行
    assert L.clean_ws("a  \r\n\r\n\r\n\r\nb\n\n") == "a\n\nb"
    assert L.clean_ws("  \n\nx\n\n  ") == "x"

    # 列表转换
    assert L.to_bullets("甲\n乙") == "- 甲\n- 乙"
    assert L.to_bullets("- 已有") == "- 已有", "已是列表项不应重复加符号"
    assert L.to_bullets("1. 有序") == "1. 有序"
    assert L.to_numbered("甲\n乙") == "1. 甲\n2. 乙"
    assert L.to_numbered("- 甲\n- 乙") == "1. 甲\n2. 乙", "应替换原列表符号"

    # 去围栏
    assert L.strip_code_fence('```json\n{"a":1}\n```') == '{"a":1}'
    assert L.strip_code_fence("普通文本") == "普通文本"

    # JSON 美化（含中文不转义）；非法 JSON 原文返回
    assert L.pretty_json('{"a":1,"b":[1,2]}') == \
        '{\n  "a": 1,\n  "b": [\n    1,\n    2\n  ]\n}'
    assert L.pretty_json('{"k":"中文"}') == '{\n  "k": "中文"\n}'
    assert L.pretty_json("不是json") == "不是json"

    # 去重（忽略首尾空白差异，保序；空行保留结构）
    assert L.dedupe_lines("a\nA\nb\na") == "a\nA\nb"
    assert L.dedupe_lines("x\n\nx") == "x\n", "重复项移除，空行结构保留"

    # URL 提取（半角/全角标点都要剥掉）
    assert L.extract_urls("见 https://a.com/x 和 http://b.cn。") == \
        "https://a.com/x\nhttp://b.cn"
    assert L.extract_urls("无链接") == ""
    assert L.extract_urls("重复 https://a.com https://a.com") == "https://a.com"

    # 中文标点转英文（已是半角不受影响；引号/括号都转）
    assert L.to_english_punct("你好，世界。测试！") == "你好,世界.测试!"
    assert L.to_english_punct('他说“好”，（真的）') == '他说"好",(真的)'
    assert L.to_english_punct("already, ascii.") == "already, ascii."

    # 删除空行（区别于 clean_ws：连单空行也删）
    assert L.remove_blank_lines("a\n\n\nb\n") == "a\nb"
    assert L.remove_blank_lines("  \nonly\n\t\n") == "only"

    # 删除 URL（脱敏/精简）；残留多空格压成单个
    s = L.strip_urls("见 https://a.com/x 和 http://b.cn。")
    assert "http" not in s
    assert "  " not in s
    assert L.strip_urls("无链接文本") == "无链接文本"

    # 未知动作原文返回
    assert L.apply("__nope__", "x") == "x"

    # 每个注册动作都能跑不抛异常
    for name in L.names():
        out = L.apply(name, "测试文本\n第二行 https://a.com")
        assert isinstance(out, str)

    print("[ok] local_actions 全部纯函数")
    print("LOCAL ACTIONS OK")


if __name__ == "__main__":
    main()
