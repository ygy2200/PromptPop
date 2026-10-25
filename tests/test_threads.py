"""线程注册表单测：QThread 运行中被 GC 会 abort，注册表必须持有引用并
在 finished 后摘除。

注意：本测试刻意创建「不会自己结束」的 QThread 来验证注册表持有引用，
结束前必须显式 quit()+wait()，否则进程退出时会触发被测的那个 bug。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from promptpop import threads  # noqa: E402
from promptpop.engine import OptimizeWorker  # noqa: E402


class _ForeverThread(QThread):
    """刻意「永不自己结束」的线程，用于验证注册表确实持有引用。

    ⚠ 用 Qt 惯用的 requestInterruption()/isInterruptionRequested()，
    **绝不要**用 QMutex 跨整个 while 循环加锁——run() 持锁期间 stop() 也去抢同一把
    非递归锁 → 谁先抢到决定生死：主线程先抢则通过，worker 先抢则**永久死锁**。
    本文件曾因此随机挂死（一次实测 >180s 未退出），一度被我误判为「环境假象」。
    """
    def run(self):
        while not self.isInterruptionRequested():
            self.msleep(20)

    def stop(self):
        self.requestInterruption()


def main():
    app = QApplication.instance() or QApplication([])

    assert threads.live_count() == 0, "初始注册表应为空"

    t = _ForeverThread()
    threads.keep_until_finished(t)
    assert threads.live_count() == 1, "登记后应有 1 个"
    t.start()
    assert t.isRunning()

    # 关键断言：即使删除所有外部引用 + 强制 GC，注册表仍持有它，不会析构
    import gc
    del t
    gc.collect()
    assert threads.live_count() == 1, "GC 后注册表仍应持有引用"

    # 结束线程 → finished → 自动摘除
    # （run() 是 msleep 轮询循环且没有事件循环，quit() 对它无效；
    #   用 requestInterruption() 让循环条件翻转为假而自然退出。）
    survivors = [x for x in gc.get_objects() if isinstance(x, _ForeverThread)]
    assert survivors, "找不到线程对象"
    real = survivors[0]
    real.stop()
    real.wait(3000)
    assert not real.isRunning()
    # finished 信号经事件循环派发，跑一圈让 lambda 执行
    app.processEvents()
    for _ in range(20):
        if threads.live_count() == 0:
            break
        app.processEvents()
        real.msleep(10)
    assert threads.live_count() == 0, "线程结束后注册表应自动摘除，实际 %d" % threads.live_count()

    print("[ok] 线程注册表：持有引用 + finished 自动摘除")

    # R8: cancel 应关闭在进行的流，使卡住的 recv 立即中断（取消近乎即时）
    class _FakeStream:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    w = OptimizeWorker([{"role": "user", "content": "x"}], "http://x/v1", "k", "m")
    fs = _FakeStream()
    w._stream = fs
    w.cancel()
    assert w._stop is True, "cancel 应置停止位"
    assert fs.closed is True, "cancel 应关闭在进行的流以打断阻塞的 recv"
    print("[ok] R8 cancel 关闭在进行的流（流式卡住时取消即时）")

    print("THREADS REGISTRY OK")


if __name__ == "__main__":
    main()
