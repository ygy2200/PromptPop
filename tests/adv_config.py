"""对抗性测试：配置坏值与数值转换（adv_*.py，AGENTS.md 对抗性验证要求）。

攻击场景：配置文件被用户/外部工具手改成坏值——裸 int()/float() 曾让取词与
优化主路径直接抛 ValueError（本文件固化前实测崩溃）；safe_int/safe_float
是统一防线。
运行： QT_QPA_PLATFORM=offscreen python tests/adv_config.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import capture  # noqa: E402
from promptpop import meta_prompt  # noqa: E402
from promptpop.config import DEFAULT_CONFIG, Config, migrate  # noqa: E402
from promptpop.util import safe_float, safe_int  # noqa: E402


def test_safe_int_matrix():
    cases = [
        ("abc", 0), (None, 0), ("", 0), ("  42 ", 42), (3.9, 3),
        (True, 1), ([], 0), ({}, 0), (object(), 0), (0, 0), (-7, -7),
    ]
    for v, want in cases:
        assert safe_int(v, 0) == want, "safe_int(%r) != %r" % (v, want)


def test_safe_float_matrix():
    cases = [
        ("abc", 0.0), (None, 0.0), ("", 0.0), ("0.5", 0.5), (0.0, 0.0),
        (True, 1.0), ([], 0.0), (object(), 0.0), (-2.5, -2.5),
    ]
    for v, want in cases:
        assert safe_float(v, 0.0) == want, "safe_float(%r) != %r" % (v, want)


def test_safe_float_zero_temperature_not_swallowed():
    # 修复点：原 `float(x or 0.3)` 会把合法的 0 温度（greedy 解码）变成 0.3
    assert safe_float(0, 0.3) == 0.0
    assert safe_float(0.0, 0.3) == 0.0


def test_pick_clipboard_delay_bad_values():
    for bad in ("abc", None, [1], {}, "1e999"):
        d = capture.pick_clipboard_delay("", {"clipboard_delay_default": bad})
        assert isinstance(d, float), "坏值 %r 应回退 float" % bad
    # 正常值仍生效
    assert capture.pick_clipboard_delay(
        "", {"clipboard_delay_default": "0.5"}) == 0.5


def test_migrate_hostile_values():
    # 坏类型字段不应让迁移崩：保留原值（上层 safe_* 读取时兜底）
    hostile = {
        "temperature": "fast",
        "max_input_chars": [1, 2],
        "api_keys": "not-a-dict",        # dict 字段给了标量
        "custom_providers": {"a": 1},    # list 字段给了 dict
        "theme": 123,
        "unknown_future_key": {"x": 1},  # 未下线的未来键 → 丢弃
    }
    out = migrate(hostile)
    assert out["temperature"] == "fast"          # 原样保留，读取侧兜底
    assert out["api_keys"] == "not-a-dict"
    assert out["config_version"] == 1
    assert "unknown_future_key" not in out
    # 迁移幂等：migrate(migrate(x)) == migrate(x)
    assert migrate(out) == out


def test_migrate_full_matrix():
    """R18 矩阵攻击：DEFAULT_CONFIG 每字段 × 10 种坏值 = 310 组合，
    migrate 必须全部不崩（坐实后固化防回归）。"""
    hostile = [None, "", "s", -1, 3.9, [], {}, [1, {"a": 2}], {"k": "v"}, True]
    for key in DEFAULT_CONFIG:
        for bad in hostile:
            data = dict(DEFAULT_CONFIG)
            data[key] = bad
            out = migrate(data)                    # 崩即失败
            assert out["config_version"] == 1


def test_migrate_dict_field_merge_attack():
    # api_keys 是 dict 字段：migrate 用 update 合并——传入超深/超宽 dict 不崩
    deep = {"k%d" % i: "v" * 100 for i in range(1000)}
    out = migrate({"api_keys": deep})
    assert out["api_keys"]["k999"] == "v" * 100


def test_config_load_corrupt_dir(tmp_path=None):
    import tempfile
    d = tempfile.mkdtemp(prefix="promptpop_adv_cfg_")
    os.environ["PROMPTPOP_CONFIG_DIR"] = d
    p = os.path.join(d, "config.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{截断的坏 JSON")
    cfg = Config.load()          # 坏 JSON：应回退 .bak/默认而非崩
    assert cfg.get("provider") == "deepseek"


def test_context_block_non_dict():
    for bad in (["a=1"], ("a",), "str", 42, set()):
        assert meta_prompt._context_block(bad) == ""
    msgs = meta_prompt.build_messages("user", "hi", "", "standard", ["bad"])
    assert "【额外约束】" not in msgs[0]["content"]


def test_custom_providers_hostile_types():
    # R21：custom_providers 被手改成非 list 曾让应用启动即崩
    # （OverlayWindow 构造路径上调 get_all_providers）
    from promptpop import providers
    for bad in ({"a": 1}, "just-str", 123, None, [1, "x", None]):
        allp = providers.get_all_providers({"custom_providers": bad})
        assert len(allp) == len(providers.PROVIDERS)     # 只剩内置三家
    mixed = providers.get_all_providers(
        {"custom_providers": [1, "x", {"id": "ok", "base_url": "https://a/v1"}]})
    assert "ok" in mixed
    d = {"custom_providers": "garbage"}
    providers.add_custom_provider(d, "N", "https://x/v1", "m")
    assert isinstance(d["custom_providers"], list) and d["custom_providers"]
    d2 = {"custom_providers": 42}
    providers.remove_custom_provider(d2, "x")
    assert d2["custom_providers"] == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
