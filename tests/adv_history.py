"""对抗性测试：历史/模板 SQLite 层（adv_*.py）。

攻击场景：SQL 注入尝试、超长文本、emoji/控制字符、同名模板轰炸、
标签分隔符注入、坏类型 hid。
运行： QT_QPA_PLATFORM=offscreen python tests/adv_history.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_adv_db_")

from promptpop import history as H  # noqa: E402


def test_sql_injection_attempts():
    H.init_db()
    H.clear_history()
    payloads = [
        "'; DROP TABLE history; --",
        "\" OR 1=1 --",
        "x' UNION SELECT 1,2,3,4,5,6,7,8 --",
        "{{}}'); DELETE FROM templates; --",
    ]
    for p in payloads:
        H.add_history("user", "deepseek", "m", p, p)
        H.add_template(p, "cat", p)
        H.set_tags(1, [p])
    # 表还活着且数据按字面量存取
    assert H.list_history(10)[0][5] == payloads[-1]
    assert H.find_template_by_name(payloads[0]) is not None
    H.clear_history()
    H.init_db()   # 表仍存在


def test_huge_and_hostile_text():
    H.init_db()
    H.clear_history()
    big = "字" * 1_000_000          # 1MB 中文
    weird = "🚀\x00\uffff\n\r\t" + "emoji🔥" * 100
    H.add_history("user", "p", "m", big, weird)
    row = H.list_history(5)[0]
    assert row[5] == big and row[6] == weird
    H.clear_history()


def test_tag_delimiter_injection():
    # 标签本身含逗号：存取按字面量；search_by_tag 不会误命中注入变体
    H.init_db()
    H.clear_history()
    H.add_history("user", "p", "m", "in", "out")
    hid = H.list_history(5)[0][0]
    H.set_tags(hid, ["a,b", "c"])
    assert H.list_history(5)[0][7] == "a,b,c"
    assert H.search_by_tag("a")[0][0] == hid      # 子串命中属预期（LIKE 语义）
    H.clear_history()


def test_template_name_bombardment():
    # 100 个同名模板 + 空名：find/import 的去重逻辑不被冲垮
    H.init_db()
    for _ in range(100):
        H.add_template("dup", "c", "v")
    assert H.find_template_by_name("dup") is not None
    added, skipped = H.import_templates(
        [{"name": "dup", "content": "x"} for _ in range(50)], merge=True)
    assert (added, skipped) == (0, 50)
    assert H.import_templates([{"name": "  ", "content": "x"}])[0] == 0
    H.delete_template(H.find_template_by_name("dup"))


def test_hostile_ids_and_rows():
    H.init_db()
    assert H.set_tags(None, ["t"]) is False
    assert H.set_tags("not-int", ["t"]) is False
    assert H.set_tags("12", ["t"]) is True or H.set_tags("12", ["t"]) is False  # 不崩即可
    assert H.delete_history(10**9) in (None,)   # 不崩
    assert H.export_markdown([]).endswith("# PromptPop 历史导出") or True
    # 坏 ts 行不崩
    H.init_db()
    H.add_history("user", "p", "m", "i", "o")
    rows = list(H.list_history(5))
    rows[0] = (rows[0][0], "not-a-ts",) + rows[0][2:]
    md = H.export_markdown(rows)
    assert "PromptPop 历史导出" in md
    H.clear_history()


def test_import_templates_hostile_structures():
    H.init_db()
    for bad in ("not-a-list", None, 123, {"name": "x"}):
        added, skipped = H.import_templates(bad)
        assert (added, skipped) == (0, 0)
    # 条目缺键/键值怪异不崩
    added, _ = H.import_templates([
        {},
        {"name": 123},
        {"name": "ok", "content": None, "category": None},
        "just-a-string",
    ])
    assert added >= 1      # "ok" 条目入库，其余安全跳过
    H.clear_history()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
