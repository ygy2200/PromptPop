"""config.import_from 格式守卫测试（纯函数，不建 QApplication）。

v0.7.7 修复：导入顶层非 JSON 对象（list/字符串）的文件时，
原实现静默 migrate 成默认配置——用户随后任意一次 save 就会把原配置整体覆盖。
现行为：抛 ValueError（设置面板已有 try/except 弹「导入失败」），内存 data 不变。
运行： QT_QPA_PLATFORM=offscreen python tests/test_config_import_guard.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from promptpop.config import Config  # noqa: E402


def _write(tmp, obj):
    p = os.path.join(tmp, "cfg.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return p


def test_import_list_raises_and_keeps_data():
    cfg = Config({"provider": "openai", "model": "my-model"})
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, ["not", "a", "dict"])
        with pytest.raises(ValueError):
            cfg.import_from(p)
    assert cfg.get("provider") == "openai"       # 内存配置不被破坏
    assert cfg.get("model") == "my-model"


def test_import_string_raises():
    cfg = Config()
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, "just a string")
        with pytest.raises(ValueError):
            cfg.import_from(p)


def test_import_valid_dict_still_works():
    cfg = Config({"model": "old"})
    with tempfile.TemporaryDirectory() as tmp:
        p = _write(tmp, {"model": "new-model", "proxy": "http://127.0.0.1:7890"})
        cfg.import_from(p)
    assert cfg.get("model") == "new-model"
    assert cfg.get("proxy") == "http://127.0.0.1:7890"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
