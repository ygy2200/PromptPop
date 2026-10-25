"""第四轮（R2–R8）测试：代理 / 错误指引 / config 迁移 / 调试日志 / 历史治理 / Esc 取消 / 缩放。

运行：QT_QPA_PLATFORM=offscreen <venv-python> tests/test_cycle4.py
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="pp_cfg4_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import Qt, QEvent, QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402

app = QApplication(sys.argv)

from promptpop import engine, debuglog, history  # noqa: E402
from promptpop.config import migrate, Config, CONFIG_VERSION, DEFAULT_CONFIG, config_dir  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402
from promptpop.engine import OptimizeWorker  # noqa: E402
from tests.mock_llm import make_mock_server  # noqa: E402

# R2 代理客户端构建（真实代理转发待确认）
c = engine.build_client("k", "http://127.0.0.1:9/v1", timeout=5, proxy="http://127.0.0.1:9")
assert c is not None and hasattr(c, "chat")
w = OptimizeWorker([{"role": "user", "content": "x"}], "http://x/v1", "k", "m",
                   proxy="http://p:1")
assert w.proxy == "http://p:1"
print("[ok] build_client(proxy) + worker.proxy (真实代理转发待确认)")

# R3 错误指引
for k in ("transient", "auth", "invalid", "unknown"):
    assert engine.error_hint(k)
assert "代理" in engine.error_hint("unknown")
# worker 失败信息含提示且不泄 Key
loop = QEventLoop()
box = {}
w2 = OptimizeWorker([{"role": "user", "content": "x"}], "http://127.0.0.1:1/v1",
                    "sk-HINTLEAK-XYZ", "m", timeout=3, max_retries=0)
w2.failed.connect(lambda e: (box.__setitem__("err", e), loop.quit()))
w2.start()
QTimer.singleShot(8000, loop.quit)
loop.exec()
# 回收线程：否则进程退出时 QThread 可能仍在运行 → "Destroyed while thread
# is still running" 警告（并行跑多套测试时尤其明显）。
w2.quit()
w2.wait(3000)
assert "提示：" in box.get("err", ""), box
assert "sk-HINTLEAK-XYZ" not in box.get("err", ""), box
print("[ok] error hints + failed msg has hint & no key leak")

# R4 config 迁移
old = {"provider": "openai", "model": "gpt", "removed_key": "x",
       "api_keys": {"deepseek": "k"}}
m = migrate(old)
assert m["provider"] == "openai" and "removed_key" not in m
assert m["config_version"] == CONFIG_VERSION
assert m["request_timeout"] == DEFAULT_CONFIG["request_timeout"]
assert m["api_keys"]["deepseek"] == "k" and m["api_keys"]["openai"] == ""
assert migrate(m) == m  # 幂等
assert migrate(None)["provider"] == "deepseek"  # 非 dict 安全
assert Config(old).get("provider") == "openai"
print("[ok] config migrate (fill/drop/version/idempotent)")

# R5 调试日志（脱敏）
logp = config_dir() / "promptpop.log"
if logp.exists():
    logp.unlink()
debuglog.configure(True)
debuglog.get_logger().info("calling with key sk-SECRET-1234567890abcd now")
for h in debuglog.get_logger().handlers:
    h.flush()
assert logp.exists()
content = logp.read_text(encoding="utf-8")
assert "calling with key" in content
assert "sk-SECRET-1234567890abcd" not in content  # 已脱敏
debuglog.configure(False)
print("[ok] debuglog writes + masks secret")

# R6 历史：固定/删除/保留清理
history.init_db()
conn = history._conn()
old_ts = time.time() - 100 * 86400
conn.execute("INSERT INTO history(ts,mode,provider,model,input,output,pinned) "
             "VALUES(?,?,?,?,?,?,?)", (old_ts, "user", "m", "m", "old-unpinned", "o", 0))
conn.execute("INSERT INTO history(ts,mode,provider,model,input,output,pinned) "
             "VALUES(?,?,?,?,?,?,?)", (old_ts, "user", "m", "m", "old-pinned", "o", 1))
conn.commit()
conn.close()
history.add_history("user", "m", "m", "recent", "o")
pruned = history.prune_history(30)
assert pruned == 1, pruned  # 只删旧的未固定
rows = history.list_history(100)
inputs = [r[5] for r in rows]
assert "old-pinned" in inputs and "recent" in inputs and "old-unpinned" not in inputs
# 删除单条
hid = [r[0] for r in rows if r[5] == "recent"][0]
history.delete_history(hid)
assert "recent" not in [r[5] for r in history.list_history(100)]
print("[ok] history prune/pin/delete")

# R7 Esc 取消进行中的流
srv, port = make_mock_server("# Role: Z")
cfg = Config()
cfg.set("provider", "ollama")
cfg.set("ollama_base_url", f"http://127.0.0.1:{port}/v1")
cfg.set("model", "m")
ov = OverlayWindow(cfg)
ov.set_input("测试")
ov._on_optimize()
assert ov.worker is not None and ov.worker.isRunning()
ov.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.KeyboardModifier.NoModifier))
assert ov.worker._stop is True  # 已发出取消
assert not ov.isVisible()        # 已隐藏
# 先等 worker 真正退出，再关 mock server：否则单线程 server 在 worker 尚未连上
# 前就被 shutdown，worker 的 recv 会永久阻塞（服务已不在），导致偶发挂死。
# （quit() 对无事件循环的 run() 是空操作，只有 wait() 有效。）
if ov.worker is not None:
    ov.worker.wait(8000)
assert not ov.worker.isRunning(), "Esc 取消后 worker 应已退出"
srv.shutdown()
print("[ok] Esc cancels active stream + hides")

# R8 缩放把手
assert len(ov._grips) == 3
ov.resize(700, 500)
ov.resizeEvent(None)
# 右下角把手应贴近右下
assert abs(ov._grips[0].x() - (ov.width() - 16)) <= 1
print("[ok] frameless resize grips present + repositioned")

print("CYCLE4 TESTS OK (R2-R8)")
