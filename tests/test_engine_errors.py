"""engine.classify_error 错误分类测试（离屏）。

R8 加固：openai SDK 可用时优先按异常类型判定 auth/invalid（消息文案随 SDK 版本变化，
文本匹配不稳）；无 SDK 或异常非该类时退化为消息文本匹配。
运行： QT_QPA_PLATFORM=offscreen python tests/test_engine_errors.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import engine  # noqa: E402


def test_transient_via_monkeypatch():
    # 与 test_rounds 一致：_transient_errors 可注入，FakeTransient 应判 transient
    engine._transient_errors = lambda: (ValueError,)
    assert engine.classify_error(ValueError("net"))[0] == "transient"


def test_auth_string_fallback():
    # 无 openai 或异常非 SDK 类时，仍按消息文本匹配
    assert engine.classify_error(Exception("Invalid API key 401"))[0] == "auth"


def test_invalid_string_fallback():
    assert engine.classify_error(Exception("400 invalid_request"))[0] == "invalid"


def test_unknown_fallback():
    assert engine.classify_error(Exception("something weird"))[0] == "unknown"


def test_openai_auth_class():
    # 真实运行时（装了 openai）应优先按异常类型判定，不受消息文案影响
    try:
        from openai import AuthenticationError
    except Exception:
        return  # 环境无 openai 则跳过（headless 可能未装）
    try:
        err = AuthenticationError("auth failed")
    except Exception:
        return
    kind, _ = engine.classify_error(err)
    assert kind == "auth"


def test_openai_badrequest_class():
    try:
        from openai import BadRequestError
    except Exception:
        return
    try:
        err = BadRequestError("bad request")
    except Exception:
        return
    kind, _ = engine.classify_error(err)
    assert kind == "invalid"


def test_openai_422_unprocessable_class():
    # R2：422 内容/参数校验失败应归 invalid（原先落 unknown → 误导成「需配代理」）
    try:
        from openai import UnprocessableEntityError
    except Exception:
        return
    try:
        err = UnprocessableEntityError("content too long")
    except Exception:
        return
    kind, _ = engine.classify_error(err)
    assert kind == "invalid"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
