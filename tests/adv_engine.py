"""对抗性测试：engine 层（adv_*.py）。

攻击场景：畸形 base_url、负超时、__str__ 抛异常的错误对象、
usage/choices 属性各路抛异常的假流 chunk、HINTS 覆盖完整性。
运行： QT_QPA_PLATFORM=offscreen python tests/adv_engine.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import engine  # noqa: E402


class WeirdError(Exception):
    def __str__(self):
        raise RuntimeError("__str__ 自己就炸")


def test_esafe_hostile_error():
    assert engine._esafe(WeirdError()) == "WeirdError"   # 不崩，退回类名
    assert engine._esafe(Exception("normal")) == "normal"


def test_classify_error_hostile_error_object():
    kind, msg = engine.classify_error(WeirdError())
    assert kind == "unknown"
    assert "WeirdError" in msg and "boom" not in msg     # 不带出内部异常


def test_is_loopback_hostile_urls():
    assert engine._is_loopback("http://localhost:11434/v1") is True
    assert engine._is_loopback("http://LOCALHOST") is True
    assert engine._is_loopback("http://127.0.0.1:8080") is True
    assert engine._is_loopback("http://[::1]:1") is True
    assert engine._is_loopback("") is True               # 空串按回环直连处理
    for remote in ("https://api.deepseek.com", "ftp://x", "//no-scheme",
                   "http://example.com", "not a url \x00", "http://0.0.0.0/x"):
        engine._is_loopback(remote)                       # 一律不崩
    assert engine._is_loopback("https://api.deepseek.com") is False


def test_build_timeout_negative_clamped():
    t = engine.build_timeout(-5, -3)
    assert t.connect >= 1.0 and t.read >= 1.0
    t2 = engine.build_timeout(0, 0)
    assert t2.connect >= 1.0 and t2.read >= 1.0
    t3 = engine.build_timeout(10.0, 60.0)                # 正常值不回归
    assert t3.connect == 10.0 and t3.read == 60.0


def test_consume_stream_hostile_chunks():
    from types import SimpleNamespace

    class Bad:
        @property
        def usage(self):
            raise RuntimeError("usage 炸")

        @property
        def choices(self):
            raise RuntimeError("choices 炸")

    ok_chunk = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"))], usage=None)
    empty_chunk = SimpleNamespace(choices=[], usage=None)

    got = []

    def on_tok(t):
        got.append(t)

    usages = []
    full, received = engine.consume_stream(
        iter([Bad(), ok_chunk, empty_chunk, Bad()]), on_tok,
        on_usage=lambda u: usages.append(u))
    assert full == "hi" and received is True and got == ["hi"]


def test_consume_stream_stop_immediately():
    full, received = engine.consume_stream(iter(["a", "b"]), lambda t: None,
                                           should_stop=lambda: True)
    assert full == "" and received is False


def test_hints_cover_all_kinds():
    for kind in ("transient", "auth", "invalid", "unknown", "not-a-kind"):
        assert engine.error_hint(kind)         # 未知 kind 也回退到 unknown 提示


def test_scrub_path_in_errors():
    from promptpop import util
    key = "sk-verysecretkey1234567890"
    msg = "Authorization failed for %s" % key
    assert key not in util.scrub_secret(msg, key)
    assert util.scrub_secret("", key) == ""
    assert util.scrub_secret("no key here", "") == "no key here"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
