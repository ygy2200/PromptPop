"""流式显示缓冲回归测试（离屏，R23 性能修复）。

原实现逐 chunk moveCursor+insert 在长文本下 O(n²)（实测 1MB 分块插入 153s）。
改为 _stream_buf 攒 chunk + 60ms 定时批量插入。本文件固化缓冲语义：
token 先攒后冲、busy 结束自动冲、judge 路径不受影响、超大文本批量插入性能。
运行： QT_QPA_PLATFORM=offscreen python tests/test_stream_buffer.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_stream_")

from PySide6.QtWidgets import QApplication  # noqa: E402

from promptpop.config import Config  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _ov():
    _app()
    ov = OverlayWindow(Config())
    return ov


def test_token_buffered_not_immediate():
    ov = _ov()
    ov._set_busy(True)
    ov._on_token("片段1")
    ov._on_token("片段2")
    # 定时器未触发时 result_box 还没有内容（攒着）
    assert ov.result_box.toPlainText() == ""
    ov._flush_stream_buf()
    assert ov.result_box.toPlainText() == "片段1片段2"


def test_busy_end_flushes_residual():
    ov = _ov()
    ov._set_busy(True)
    ov._on_token("残留内容")
    ov._set_busy(False)              # 结束（含失败/取消）自动冲缓冲
    assert ov.result_box.toPlainText() == "残留内容"
    assert not ov._stream_timer.isActive()


def test_judge_path_unaffected():
    ov = _ov()
    ov._set_busy(True)
    ov._run_kind = "judge"
    ov._on_token("评审")
    assert ov._judge_buf == "评审"
    ov._flush_stream_buf()
    assert ov.result_box.toPlainText() == ""   # judge 不进结果框
    ov._set_busy(False)


def test_bulk_insert_performance():
    """1MB 分批插入（缓冲后 60ms/批）应在数秒内完成——修复前为 153s。"""
    ov = _ov()
    ov._set_busy(True)
    t0 = time.time()
    n, batch = 0, "字" * 4096
    while n < 1024 * 1024:             # 1MB
        ov._on_token(batch)
        n += len(batch)
        if len(ov._stream_buf) >= 8:   # 模拟 60ms 定时粒度的批量
            ov._flush_stream_buf()
    ov._flush_stream_buf()
    dt = time.time() - t0
    assert len(ov.result_box.toPlainText()) == 1024 * 1024
    assert dt < 20.0, "1MB 显示耗时 %.1fs（>20s 说明 O(n²) 回归）" % dt


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
