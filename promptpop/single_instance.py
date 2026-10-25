"""单实例守护（QLockFile，跨平台、自动处理崩溃残留锁）。"""
from PySide6.QtCore import QLockFile, QDir

_APP_KEY = "PromptPop_single_instance"


def _lock_path():
    return QDir.temp().absoluteFilePath(_APP_KEY + ".lock")


def acquire(wait_ms=50):
    """尝试取锁。返回 (lock, ok)；ok=True 为首个实例。调用方须持有 lock 防 GC。"""
    lf = QLockFile(_lock_path())
    ok = lf.tryLock(wait_ms)
    return lf, ok


def release(lock):
    if lock is not None:
        try:
            lock.unlock()
        except Exception:
            pass
