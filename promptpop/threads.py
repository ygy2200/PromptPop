"""短寿命 QThread 的安全持有：模块级注册表。

背景：QThread 在**运行中**被 GC / 析构会触发
`QThread: Destroyed while thread is still running` → qFatal → 进程 abort。

典型触发：线程引用只挂在「可能先销毁」的父对象上——例如模态设置对话框
（`exec()` 返回即析构），此时线程还在飞，随对话框释放的引用一没就被析构。

注册表本身随进程存活，因此期间一定有人持有引用；`finished` 信号到达时
线程已结束，再从注册表摘除，让其被安全 GC。

用法：
    from . import threads
    th = SomeThread(...)
    th.some_signal.connect(handler)
    threads.keep_until_finished(th)
    th.start()
"""
_LIVE = []


def keep_until_finished(th):
    """登记线程；finished 后自动摘除（届时线程已结束，可安全回收）。"""
    if th is None:
        return
    _LIVE.append(th)
    try:
        th.finished.connect(lambda: _discard(th))
    except Exception:
        pass


def _discard(th):
    try:
        _LIVE.remove(th)
    except ValueError:
        pass


def live_count():
    return len(_LIVE)
