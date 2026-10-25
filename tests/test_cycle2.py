"""新一轮（R2–R8）测试：mock LLM 端到端 + 后处理/单实例/探活/定位/历史/模板变量。

运行：QT_QPA_PLATFORM=offscreen <venv-python> tests/test_cycle2.py
"""
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

app = QApplication(sys.argv)

from promptpop import postprocess, single_instance, ollama_probe, util, history  # noqa: E402
from promptpop.config import Config  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402
from promptpop.engine import OptimizeWorker  # noqa: E402
from tests.mock_llm import make_mock_server  # noqa: E402

# ---------- R3 后处理 ----------
assert postprocess.strip_fences("```md\n# X\n```") == "# X"
assert postprocess.strip_fences("```json\n{\"a\":1}") == '{"a":1}'   # 悬空开围栏
assert postprocess.strip_fences("~~~\n# Y\n~~~") == "# Y"
assert postprocess.postprocess_output("  \n# Role: X\n  ") == "# Role: X"
assert postprocess.postprocess_output("the `inline` stays") == "the `inline` stays"
r = postprocess.postprocess_output("Sure, here's the result\n# Role: Z")
assert r.startswith("result") and "# Role: Z" in r
print("[ok] postprocess (fences/prefix/trim)")

# ---------- R6 定位夹取 ----------
assert util.clamp_position(5, 5, 100, 50, 0, 0, 200, 200) == (8, 8)
assert util.clamp_position(190, 190, 100, 50, 0, 0, 200, 200) == (92, 142)
assert util.clamp_position(50, 50, 100, 50, 0, 0, 200, 200) == (50, 50)
print("[ok] util.clamp_position")

# ---------- R8 模板变量 ----------
assert util.extract_vars("a {{name}} b {{name}} {{lang}}") == ["name", "lang"]
assert util.extract_vars("任务：{{任务描述}}") == ["任务描述"]
assert util.render_template("hi {{name}}", {"name": "Y"}) == "hi Y"
assert util.render_template("hi {{name}}", {}) == "hi {{name}}"
print("[ok] util template vars")

# ---------- R7 历史过滤 ----------
rows = [(1, 0, "user", "deepseek", "m", "写周报", "# Role"),
        (2, 0, "system", "ollama", "m2", "翻译文本", "x")]
assert len(util.filter_history(rows, "")) == 2
assert util.filter_history(rows, "ollama") == [rows[1]]
assert util.filter_history(rows, "周报") == [rows[0]]
print("[ok] util.filter_history")

# ---------- R5 Ollama 探活 ----------
class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"models":[{"name":"qwen"}]}')


srv = HTTPServer(("127.0.0.1", 0), _H)
oport = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
assert ollama_probe._tags_url(f"http://127.0.0.1:{oport}/v1") == f"http://127.0.0.1:{oport}/api/tags"
assert ollama_probe.is_ollama_up(f"http://127.0.0.1:{oport}/v1") is True
assert ollama_probe.ollama_models(f"http://127.0.0.1:{oport}/v1") == ["qwen"]
assert ollama_probe.is_ollama_up("http://127.0.0.1:1/v1", timeout=1) is False
srv.shutdown()
print("[ok] ollama_probe (up/down/models/tags_url)")

# ---------- R4 单实例 ----------
lf1, ok1 = single_instance.acquire()
if not ok1:
    # 锁被外部占用（如真机正在运行 PromptPop.exe）——测试环境与运行实例冲突，
    # 跳过而非失败（真机单实例行为已由实际运行的双开拦截验证）
    print("[skip] 单实例：锁被外部运行中的 PromptPop 占用")
else:
    lf2, ok2 = single_instance.acquire()
    assert ok2 is False
    single_instance.release(lf1)
if ok1:
    lf3, ok3 = single_instance.acquire()
    assert ok3 is True
    single_instance.release(lf3)
    print("[ok] single_instance acquire/release")

# ---------- R2 端到端：OptimizeWorker 直连 mock（真实 SDK 流式路径） ----------
srv2, port2 = make_mock_server("# Role: 周报助手\n## Profile")
base = f"http://127.0.0.1:{port2}/v1"
res = {}
w = OptimizeWorker([{"role": "user", "content": "帮我写周报"}], base, "mock", "mock:latest",
                   timeout=10)
loop = QEventLoop()
w.done.connect(lambda f: (res.__setitem__("done", f), loop.quit()))
w.failed.connect(lambda e: (res.__setitem__("err", e), loop.quit()))
w.start()
QTimer.singleShot(10000, loop.quit)
loop.exec()
w.quit(); w.wait(3000)   # 回收线程，防进程退出时 QThread 运行中析构
assert res.get("done") and "# Role: 周报助手" in res["done"], res
srv2.shutdown()
print("[ok] R2 e2e: OptimizeWorker -> mock (real SDK streaming)")

# ---------- R2 端到端：Overlay 全流程（ollama 指向 mock，无 Key） ----------
srv3, port3 = make_mock_server("```markdown\n# Role: 测试\n## Profile\n- 会做 X\n```")
cfg = Config()
cfg.set("provider", "ollama")
cfg.set("ollama_base_url", f"http://127.0.0.1:{port3}/v1")
cfg.set("model", "mock:latest")
ov = OverlayWindow(cfg)
ov.set_input("把这段话优化一下")
ov._on_optimize()
wk = ov.worker
assert wk is not None, "worker 未创建（可能被 Ollama 探活/Key 检查拦截）"
loop2 = QEventLoop()
wk.done.connect(loop2.quit)
wk.failed.connect(lambda e: (res.__setitem__("ov_err", e), loop2.quit()))
QTimer.singleShot(10000, loop2.quit)
loop2.exec()
assert "ov_err" not in res, res.get("ov_err")
txt = ov.result_box.toPlainText()
assert "# Role: 测试" in txt, txt
assert "```" not in txt, "后处理应去掉围栏: " + txt
assert any(h[5] == "把这段话优化一下" for h in history.list_history(5)), "应入库"
srv3.shutdown()
print("[ok] R2 e2e: Overlay 全流程(取词->优化->后处理->入库), 无 Key")

print("CYCLE2 TESTS OK (R2-R8)")
