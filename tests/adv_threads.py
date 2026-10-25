"""对抗性测试：线程注册表并发（adv_*.py）。

攻击场景：多线程并发 keep/摘除、重复登记、None、finished 后的引用清理。
运行： QT_QPA_PLATFORM=offscreen python tests/adv_threads.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread  # noqa: E402

from promptpop import threads  # noqa: E402


class _NoopThread(QThread):
    def run(self):
        pass


def test_keep_none_and_live_count():
    before = threads.live_count()
    threads.keep_until_finished(None)          # None 不崩
    assert threads.live_count() == before


def test_concurrent_keep_discard():
    th = _NoopThread()
    base = threads.live_count()
    stop = threading.Event()

    def keeper():
        while not stop.is_set():
            threads.keep_until_finished(th)

    def discarder():
        while not stop.is_set():
            threads._discard(th)               # 反复摘除（ValueError 内部吞掉）

    ks = [threading.Thread(target=keeper, daemon=True) for _ in range(4)]
    ds = [threading.Thread(target=discarder, daemon=True) for _ in range(4)]
    for t in ks + ds:
        t.start()
    for _ in range(50):
        n = threads.live_count()
        assert n >= base                        # 计数永不复数为负
    stop.set()
    for t in ks + ds:
        t.join(timeout=5)
    # 收尾：把并发期间累积的引用清干净（同对象多引用全摘）
    for _ in range(threads.live_count() - base):
        threads._discard(th)
    assert threads.live_count() == base


def test_double_keep_then_discard_all():
    th = _NoopThread()
    base = threads.live_count()
    threads.keep_until_finished(th)
    threads.keep_until_finished(th)            # 重复登记：两条引用
    assert threads.live_count() == base + 2
    threads._discard(th)
    threads._discard(th)
    threads._discard(th)                        # 多摘不崩（ValueError 吞掉）
    assert threads.live_count() == base


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
