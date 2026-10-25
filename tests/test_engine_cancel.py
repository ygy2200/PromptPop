"""OptimizeWorker 取消时机测试（无 QApplication：QThread.run 同步在子线程执行）。

v0.7.7 修复：重试退避（_stop_event.wait）中用户取消后，原实现仍 continue 发起
下一轮真实 API 请求（prompt token 已计费风险）。现行为：退避中取消 → 直接
cancelled + return。本文件固化：①取消后 create 只被调 1 次；②对照——不取消时
重试确实发生（calls==2），证明 ① 不是「根本没重试」造成的假阳性。
运行： QT_QPA_PLATFORM=offscreen python tests/test_engine_cancel.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import engine  # noqa: E402


class FakeTransient(Exception):
    pass


class _Completions:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.calls += 1
        raise FakeTransient("connection reset")


class _Chat:
    def __init__(self, outer):
        self.completions = _Completions(outer)


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.chat = _Chat(self)

    def close(self):
        pass


def _make_worker(fake, max_retries):
    engine._transient_errors = lambda: (FakeTransient,)
    engine.build_client = lambda *a, **k: fake
    return engine.OptimizeWorker(
        [{"role": "user", "content": "x"}], "http://127.0.0.1:9", "key",
        "model", max_retries=max_retries)


def test_cancel_during_backoff_stops_retry():
    fake = FakeClient()
    w = _make_worker(fake, max_retries=5)
    th = threading.Thread(target=w.run, daemon=True)
    th.start()
    time.sleep(0.4)          # 第一次 create 已失败，run 正处于退避等待中
    w.cancel()
    th.join(timeout=10)
    assert not th.is_alive(), "取消后 worker 线程未退出"
    assert fake.calls == 1, "退避中取消后不应再发起第 %d 轮请求" % fake.calls


def test_without_cancel_retry_happens():
    fake = FakeClient()
    w = _make_worker(fake, max_retries=1)
    th = threading.Thread(target=w.run, daemon=True)
    th.start()
    th.join(timeout=30)
    assert not th.is_alive()
    assert fake.calls == 2, "不取消时应重试一次（calls=%d）" % fake.calls


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
