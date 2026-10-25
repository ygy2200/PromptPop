"""第 2–8 轮增量单测：引擎健壮性 / 剪贴板安全 / 降智 / keyring / 变体与评审。

运行：QT_QPA_PLATFORM=offscreen <venv-python> tests/test_rounds.py
不启动全局钩子、不发真实按键（用假发送器）、keyring 用本机 Windows 钥匙串并清理。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication(sys.argv)

from promptpop import engine, capture, actions, secrets  # noqa: E402
from promptpop.meta_prompt import get_meta_template, build_judge_messages  # noqa: E402
from promptpop.config import Config  # noqa: E402

# ---------- 1) 引擎错误分类 ----------
class FakeTransient(Exception):
    pass


engine._transient_errors = lambda: (FakeTransient,)
assert engine.classify_error(FakeTransient("net"))[0] == "transient"
assert engine.classify_error(Exception("Invalid API key 401"))[0] == "auth"
assert engine.classify_error(Exception("400 invalid_request"))[0] == "invalid"
assert engine.classify_error(Exception("something weird"))[0] == "unknown"
print("[ok] engine.classify_error")

# ---------- 2) 流消费 + 取消 ----------
class _Delta:
    def __init__(self, c):
        self.content = c


class _Choice:
    def __init__(self, c):
        self.delta = _Delta(c)


class _Chunk:
    def __init__(self, c):
        self.choices = [_Choice(c)]


got = []
full, _ = engine.consume_stream(iter([_Chunk("a"), _Chunk("b"), _Chunk("c")]),
                               got.append)
assert full == "abc" and got == ["a", "b", "c"]
# 取消：第 2 个 token 后停止
state = {"n": 0}


def stop_after_two():
    state["n"] += 1
    return state["n"] > 2


part, _ = engine.consume_stream(iter([_Chunk("x"), _Chunk("y"), _Chunk("z")]),
                                 lambda t: None, stop_after_two)
assert part == "xy", part
print("[ok] engine.consume_stream + cancel")

# ---------- 3) 剪贴板降智判定（只对 I-beam/unknown 走，arrow/hand/custom 跳过） ----------
assert capture.should_attempt_clipboard("ibeam", "", []) is True
assert capture.should_attempt_clipboard("unknown", "", []) is True
assert capture.should_attempt_clipboard("arrow", "", []) is False
assert capture.should_attempt_clipboard("hand", "", []) is False
assert capture.should_attempt_clipboard("custom", "", []) is False
assert capture.should_attempt_clipboard("custom", "acrobat.exe", ["acrobat.exe"]) is True
assert capture.should_attempt_clipboard("custom", "chrome.exe", ["acrobat.exe"]) is False
print("[ok] capture.should_attempt_clipboard")

# ---------- 4) 剪贴板回退：总是备份/还原（假剪贴板 + 假发送，不发真实键） ----------
_orig_get, _orig_set = actions.clipboard_get_text, actions.clipboard_set_text
_orig_ci, _orig_cc, _orig_html = (capture._send_ctrl_insert, capture._send_ctrl_c,
                                  capture._clipboard_get_html)
clip = {"v": "USER_ORIGINAL"}
actions.clipboard_get_text = lambda: clip["v"]
actions.clipboard_set_text = lambda t: clip.__setitem__("v", t)
capture._clipboard_get_html = lambda: ""

# 4a) 无选中：Ctrl+C 无副作用 → 取不到 → 还原原剪贴板
capture._send_ctrl_insert = lambda: None
capture._send_ctrl_c = lambda: None
r = capture.extract_clipboard({}, "chrome.exe")
assert r is None and clip["v"] == "USER_ORIGINAL", (r, clip)

# 4b) 有选中：假发送器模拟应用把选中写进剪贴板 → 取到 → 仍还原原剪贴板
def fake_insert():
    clip["v"] = "SELECTED_TEXT"
capture._send_ctrl_insert = fake_insert
r = capture.extract_clipboard({}, "chrome.exe")
assert r == "SELECTED_TEXT" and clip["v"] == "USER_ORIGINAL", (r, clip)

# 4c) delay-read 程序用更长延时（不应报错，仅验证可运行）
r2 = capture.extract_clipboard({"clipboard_delay_read": ["acrobat.exe"]}, "acrobat.exe")
assert r2 in (None, "SELECTED_TEXT")

actions.clipboard_get_text, actions.clipboard_set_text = _orig_get, _orig_set
capture._send_ctrl_insert, capture._send_ctrl_c, capture._clipboard_get_html = (_orig_ci, _orig_cc, _orig_html)
print("[ok] capture.extract_clipboard backup/restore (faked)")

# ---------- 5) 系统探针返回类型（真实行为待真机确认） ----------
assert capture.cursor_kind() in ("ibeam", "arrow", "hand", "custom", "unknown")
assert isinstance(capture.is_fullscreen_exclusive(), bool)
assert isinstance(capture.foreground_program(), str)
print("[ok] capture probes return valid types (real behavior 待真机确认)")

# ---------- 6) keyring 往返 + 迁移 ----------
# headless 环境（CI/离屏）无钥匙串后端：跳过而非失败——真机带 WinVault 后端仍全量验证，
# 不让环境限制作为长期红项稀释回归信号（v0.7.8 R8，此前每次全量必红）
if not secrets.backend_available():
    print("[skip] secrets keyring round-trip (headless: no keyring backend)")
else:
    secrets.set_key("deepseek", "test-key-abc123")
    assert secrets.get_key("deepseek") == "test-key-abc123"
    assert secrets.has_key("deepseek") is True
    # resolve_api_key：keyring 优先
    assert secrets.resolve_api_key({"api_keys": {"deepseek": "cfgfallback"}}, "deepseek") == "test-key-abc123"
    # 迁移：config 明文 → keyring，config 清空
    cfg = Config()
    cfg.set("api_keys", {"deepseek": "", "openai": "migrate-test-999"})
    moved = secrets.migrate_plaintext_to_keyring(cfg)
    assert moved >= 1 and secrets.get_key("openai") == "migrate-test-999"
    assert cfg.get("api_keys")["openai"] == ""
    # 清理测试密钥
    secrets.set_key("deepseek", "")
    secrets.set_key("openai", "")
    assert secrets.get_key("deepseek") == "" and secrets.get_key("openai") == ""
    print("[ok] secrets keyring round-trip + migrate (WinVaultKeyring)")

# ---------- 7) meta 变体 + 评审 ----------
assert "精简" in get_meta_template("user", "", "concise")
assert get_meta_template("user", "CUSTOM", "strict").startswith("CUSTOM")
assert "严格" in get_meta_template("user", "CUSTOM", "strict")
jm = build_judge_messages("原始", "优化后")
assert jm[0]["role"] == "system" and "原始" in jm[1]["content"] and "优化后" in jm[1]["content"]
print("[ok] meta variants + judge messages")

# ---------- 8) insert_after 存在（不调用，避免发真实键） ----------
assert callable(actions.insert_after) and callable(actions.replace_selection)
print("[ok] actions.insert_after/replace_selection present")

print("ROUNDS TESTS OK (2-8)")
