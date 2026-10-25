"""第三轮（R2–R8）测试：模型列表 / token 用量 / Key 脱敏 / 校验 / 托盘图标 / 重试端到端。

运行：QT_QPA_PLATFORM=offscreen <venv-python> tests/test_cycle3.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="pp_cfg_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

app = QApplication(sys.argv)

from promptpop import engine, util  # noqa: E402
from promptpop.config import Config  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402
from promptpop.engine import OptimizeWorker  # noqa: E402
from promptpop import app as appmod  # noqa: E402
from tests.mock_llm import make_mock_server  # noqa: E402


def run_worker(w, timeout_ms):
    loop = QEventLoop()
    box = {}
    w.done.connect(lambda f: (box.__setitem__("done", f), loop.quit()))
    w.failed.connect(lambda e: (box.__setitem__("err", e), loop.quit()))
    w.usage.connect(lambda u: box.__setitem__("usage", u))
    w.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    w.quit(); w.wait(3000)   # 回收线程，防进程退出时 QThread 运行中析构
    return box


# R2 模型列表
srv, port = make_mock_server(models=["mock:latest", "mock:pro", "deepseek-chat"])
assert engine.list_models(f"http://127.0.0.1:{port}/v1", "k") == \
    ["mock:latest", "mock:pro", "deepseek-chat"]
srv.shutdown()
print("[ok] engine.list_models")

# R5 校验
assert util.validate_temperature("0.3") == 0.3
assert util.validate_temperature("abc") is None
assert util.validate_temperature("5") is None
assert util.validate_base_url("http://x/v1") is True
assert util.validate_base_url("ftp://x") is False
print("[ok] util.validate_*")

# R4 脱敏
assert "sk-abc" not in util.scrub_secret("err with sk-abc inside", "sk-abc")
assert util.mask_secret("sk-1234567890") == "sk-...7890"
print("[ok] util.scrub_secret / mask_secret")

# R6 托盘图标
assert not appmod.make_icon().isNull()
print("[ok] make_icon not null")

# R3 token 用量
srv2, p2 = make_mock_server("# Role: X", usage=True)
box = run_worker(OptimizeWorker([{"role": "user", "content": "x"}],
                                f"http://127.0.0.1:{p2}/v1", "k", "m", timeout=10), 10000)
assert box.get("usage", {}).get("total_tokens") == 19, box
srv2.shutdown()
print("[ok] token usage via worker:", box.get("usage"))

# R4 worker 失败不泄 Key
box2 = run_worker(OptimizeWorker([{"role": "user", "content": "x"}],
                                 "http://127.0.0.1:1/v1", "sk-SECRET-LEAK-XYZ", "m",
                                 timeout=3, max_retries=0), 8000)
assert "sk-SECRET-LEAK-XYZ" not in box2.get("err", ""), box2
print("[ok] worker failed no key leak:", (box2.get("err") or "")[:60])

# R8 重试端到端：首次 503 → 重试 → 成功
srv3, p3 = make_mock_server("# Role: 重试成功", usage=False, fail_first=1)
box3 = run_worker(OptimizeWorker([{"role": "user", "content": "x"}],
                                 f"http://127.0.0.1:{p3}/v1", "k", "m",
                                 timeout=8, max_retries=2), 20000)
assert box3.get("done") and "重试成功" in box3["done"], box3
srv3.shutdown()
print("[ok] R8 retry e2e (503 -> retry -> success)")

# R2 + R7 overlay：模型填充 + 重新生成端到端
srv4, p4 = make_mock_server("# Role: Y", models=["m1", "m2"])
cfg = Config()
cfg.set("provider", "ollama")
cfg.set("ollama_base_url", f"http://127.0.0.1:{p4}/v1")
cfg.set("model", "m1")
ov = OverlayWindow(cfg)
ov._on_models_fetched(["m1", "m2", "m3"])
assert ov.model_box.count() == 3 and ov.model_box.currentText() == "m1"
ov.set_input("测试")
ov._on_regenerate()
assert ov.worker is not None
loop4 = QEventLoop()
ov.worker.done.connect(loop4.quit)
ov.worker.failed.connect(lambda e: loop4.quit())
QTimer.singleShot(10000, loop4.quit)
loop4.exec()
assert "# Role: Y" in ov.result_box.toPlainText()
srv4.shutdown()
print("[ok] R2/R7 overlay model-fetch + regenerate e2e")

print("CYCLE3 TESTS OK (R2-R8)")
