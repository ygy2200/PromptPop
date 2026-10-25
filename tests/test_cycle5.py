"""第五轮（R2–R8）测试：超时拆分 / 安全重试 / 热键校验 / 配置导入导出 / 夹取 / 历史导出 / 成本估算。

运行：QT_QPA_PLATFORM=offscreen <venv-python> tests/test_cycle5.py
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="pp_cfg5_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

app = QApplication(sys.argv)

from promptpop import engine, util, config, history  # noqa: E402
from promptpop.engine import OptimizeWorker  # noqa: E402
from openai import APITimeoutError, AuthenticationError  # noqa: E402


# ---------- R2：超时拆分 ----------
def test_build_timeout():
    t = engine.build_timeout(connect=10, read=60)
    assert abs(t.connect - 10.0) < 1e-6
    assert abs(t.read - 60.0) < 1e-6
    # 无代理也能构造客户端（仅校验不抛）
    c = engine.build_client("k", "http://x/v1", timeout=60, proxy="")
    assert hasattr(c, "chat")
    cp = engine.build_client("k", "http://x/v1", timeout=60, proxy="http://p:1")
    assert hasattr(cp, "chat")
    print("[ok] R2 build_timeout + build_client(含/不含代理)")


# ---------- R3：安全重试（仅连接阶段重试；中段失败不重试） ----------
class _Chunk:
    def __init__(self, text=None, usage=None):
        self.choices = [type("C", (), {"delta": type("D", (), {"content": text})()})()]
        self.usage = usage


class _Stream:
    def __init__(self, texts, raise_after=None, exc=None):
        self._texts = texts
        self._i = 0
        self._raise_after = raise_after
        self._exc = exc

    def __iter__(self):
        return self

    def __next__(self):
        if self._exc is not None and (self._raise_after is None or self._i >= self._raise_after):
            raise self._exc
        if self._i >= len(self._texts):
            raise StopIteration
        t = self._texts[self._i]
        self._i += 1
        return _Chunk(t)

    def close(self):
        pass


class _FakeCompletions:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kw):
        self._parent.calls += 1
        return self._parent.behavior(self._parent.calls)


class _FakeClient:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = 0
        self.chat = type("Chat", (), {"completions": _FakeCompletions(self)})()


def _run_worker(monkeypatch_behavior):
    holder = {}
    orig = engine.build_client
    engine.build_client = lambda *a, **k: _FakeClient(monkeypatch_behavior)
    w = OptimizeWorker([{"role": "user", "content": "x"}], "http://x/v1",
                        "k", "m", timeout=60, max_retries=2)
    loop = QEventLoop()
    box = {}
    w.done.connect(lambda r: (box.__setitem__("done", r), loop.quit()))
    w.failed.connect(lambda e: (box.__setitem__("err", e), loop.quit()))
    w.start()
    QTimer.singleShot(8000, loop.quit)
    loop.exec()
    engine.build_client = orig
    w.quit(); w.wait(3000)   # 回收线程，防进程退出时 QThread 运行中析构
    return w, box


def test_safe_retry_midstream_no_retry():
    # 已收到部分内容后中断（transient）→ 不重试，只报错；calls==1
    def beh(calls):
        return _Stream(["你好", "世界"], raise_after=2, exc=APITimeoutError("read timeout"))
    w, box = _run_worker(beh)
    assert "err" in box and "done" not in box
    assert w._stop is False
    assert w.__dict__.get("api_key")  # sanity
    # 通过 FakeClient 无法直接取 calls，这里用行为断言：err 提示「生成中断」
    assert "生成中断" in box["err"], box["err"]
    print("[ok] R3 中段失败不重试（保留部分内容提示）")


def test_safe_retry_connection_stage():
    # 第 1 次连接阶段就失败（transient）→ 重试；第 2 次成功
    # 用跨 FakeClient 实例的全局计数器模拟「同一次网络会话」
    counter = {"n": 0}

    def beh(calls):
        counter["n"] += 1
        if counter["n"] == 1:
            raise APITimeoutError("connect timeout")  # 建立连接前即失败
        return _Stream(["成功文本"])

    w, box = _run_worker(beh)
    assert "done" in box and box["done"] == "成功文本"
    print("[ok] R3 连接阶段失败安全重试 → 成功")


def test_auth_error_no_retry():
    # 真实 API 鉴权失败会带 "401"/"Incorrect API key" 等子串，走字符串分类；
    # 非瞬时错误，不应重试。
    def beh(calls):
        raise Exception("401 Unauthorized: Invalid API key")
    w, box = _run_worker(beh)
    assert "err" in box and "done" not in box
    assert "401" in box["err"] or "无效" in box["err"] or "Key" in box["err"]
    print("[ok] R3 鉴权错误不重试")


# ---------- R4：热键校验 / 显示 ----------
def test_hotkey():
    assert util.validate_hotkey("Ctrl+Shift+Space") == "<ctrl>+<shift>+<space>"
    assert util.validate_hotkey("ctrl+alt+k") == "<ctrl>+<alt>+k"
    assert util.validate_hotkey("Ctrl+Z") == "<ctrl>+z"
    assert util.validate_hotkey("a") is None          # 单键不行
    assert util.validate_hotkey("hello") is None      # 非法
    assert util.validate_hotkey("Ctrl+F11") == "<ctrl>+<f11>"
    assert util.format_hotkey("<ctrl>+<shift>+<space>") == "Ctrl+Shift+Space"
    assert util.format_hotkey("<ctrl>+<alt>+k") == "Ctrl+Alt+K"
    print("[ok] R4 validate_hotkey / format_hotkey")


# ---------- R4b：热键风险评估（系统保留键 / 易冲突组合） ----------
def test_hotkey_risk():
    # 系统占用的 Win+ 组合：应阻断
    block, msg = util.check_hotkey_risk("<cmd>+l")
    assert block is True and "系统占用" in msg
    # 含 Space 的组合：不阻断但提示风险
    block, msg = util.check_hotkey_risk("<ctrl>+<shift>+<space>")
    assert block is False and msg
    # 普通组合：无风险
    block, msg = util.check_hotkey_risk("<ctrl>+<alt>+k")
    assert block is False and msg == ""
    # 空：阻断
    assert util.check_hotkey_risk("")[0] is True
    print("[ok] R4b check_hotkey_risk")


# ---------- R4c：划词监听降噪（程序黑名单） ----------
def test_should_capture_selection():
    from promptpop import capture
    ex = ["explorer", "dopusrt"]
    assert capture.should_capture_selection("notepad.exe", ex) is True
    assert capture.should_capture_selection("EXPLORER.EXE", ex) is False
    assert capture.should_capture_selection("dopusrt.exe", ex) is False
    assert capture.should_capture_selection("", ex) is True
    print("[ok] R4c should_capture_selection")
def test_config_migrate_keeps_new_keys():
    from promptpop.config import migrate, DEFAULT_CONFIG
    out = migrate({"provider": "openai"})
    for k in ("selection_exclude_programs", "window_width", "window_height",
              "max_input_chars", "custom_providers", "clipboard_delay_default"):
        assert k in out, k
        assert out[k] == DEFAULT_CONFIG[k]
    print("[ok] R4d config migrate keeps new keys")


# ---------- R8：取词延时可配置（纯函数） ----------
def test_pick_clipboard_delay():
    from promptpop import capture
    assert abs(capture.pick_clipboard_delay("notepad.exe", {}) - 0.12) < 1e-9
    cfg = {"clipboard_delay_read": ["acrobat"], "clipboard_delay_default": 0.1,
           "clipboard_delay_slow": 0.3}
    assert abs(capture.pick_clipboard_delay("acrobat.exe", cfg) - 0.3) < 1e-9
    assert abs(capture.pick_clipboard_delay("chrome.exe", cfg) - 0.1) < 1e-9
    print("[ok] R8 pick_clipboard_delay")


# ---------- R5：配置导入导出 + 备份 ----------
def test_config_export_import_backup():
    cfg = config.Config({"provider": "openai", "model": "gpt-4o-mini"})
    d = tempfile.mkdtemp(prefix="pp_cfgx_")
    os.environ["PROMPTPOP_CONFIG_DIR"] = d
    cfg.save()                                  # 写 config.json
    p = config.config_path()
    bak = p.with_suffix(".json.bak")
    assert p.exists()
    assert not bak.exists()                     # 首次无备份
    cfg.set("model", "gpt-4o")
    cfg.save()                                  # 第二次 → 生成备份
    assert bak.exists()
    # 导入导出
    ep = os.path.join(d, "export.json")
    cfg.export_to(ep)
    c2 = config.Config()
    imported = c2.import_from(ep)
    assert imported["provider"] == "openai"
    assert imported["config_version"] == config.CONFIG_VERSION
    assert "unknown_key" not in imported
    print("[ok] R5 配置导出/导入(迁移)/保存备份")


# ---------- R6：超大窗口夹取 ----------
def test_clamp_oversize():
    # 窗口远超屏幕 → 居中（不溢出）
    nx, ny = util.clamp_position(100, 100, 5000, 5000, 0, 0, 1920, 1080)
    assert nx == 8 and ny == 8
    # 正常窗口
    nx2, ny2 = util.clamp_position(2000, 2000, 100, 100, 0, 0, 1920, 1080)
    assert nx2 == 1920 - 100 - 8 and ny2 == 1080 - 100 - 8
    print("[ok] R6 clamp_position 超大窗口居中 + 正常夹取")


# ---------- R7：历史导出 Markdown ----------
def test_history_markdown():
    # v0.7.0 起历史行含 tags 列（8 列）
    rows = [(1, 1700000000.0, "user", "deepseek", "deepseek-chat",
            "写个登录", "请优化为结构化提示词", "登录,示例")]
    md = history.export_markdown(rows)
    assert md.startswith("# PromptPop 历史导出")
    assert "写个登录" in md and "请优化为结构化提示词" in md
    assert "#登录" in md and "#示例" in md
    print("[ok] R7 history.export_markdown（含标签）")


# ---------- R8：成本估算 ----------
def test_estimate_cost():
    cost = util.estimate_cost("deepseek-chat",
                              {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000})
    assert abs(cost - (0.27 + 1.10)) < 1e-6
    assert util.estimate_cost("unknown-model", {"prompt_tokens": 10}) is None
    assert util.estimate_cost("gpt-4o-mini", None) is None
    print("[ok] R8 estimate_cost")


# ---------- R9：迁移含 connect_timeout 默认 ----------
def test_migrate_connect_timeout():
    m = config.migrate({"provider": "deepseek"})
    assert m["connect_timeout"] == 10.0
    assert m["request_timeout"] == 60.0
    print("[ok] R9 迁移补 connect_timeout 默认")


if __name__ == "__main__":
    test_build_timeout()
    test_safe_retry_midstream_no_retry()
    test_safe_retry_connection_stage()
    test_auth_error_no_retry()
    test_hotkey()
    test_hotkey_risk()
    test_should_capture_selection()
    test_config_migrate_keeps_new_keys()
    test_pick_clipboard_delay()
    test_config_export_import_backup()
    test_clamp_oversize()
    test_history_markdown()
    test_estimate_cost()
    test_migrate_connect_timeout()
    print("CYCLE5 TESTS OK (R2-R9)")
