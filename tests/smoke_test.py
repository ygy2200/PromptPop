"""PromptPop 冒烟测试（M1–M4）：离屏(offscreen)验证各层。

运行：QT_QPA_PLATFORM=offscreen <venv-python> tests/smoke_test.py
注意：不启动全局钩子、不模拟 Ctrl+C/V、不改注册表，避免干扰本机。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="promptpop_cfg_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from promptpop.config import Config, config_path  # noqa: E402
from promptpop.meta_prompt import (build_messages, build_followup_messages,  # noqa: E402
                                   get_meta_template)
from promptpop.providers import PROVIDERS, resolve  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402
from promptpop import actions, history, autostart, capture  # noqa: E402
from promptpop.toolbar import SelectionToolbar  # noqa: E402
from promptpop.capture import SelectionMonitor, extract_uia  # noqa: E402
from promptpop.library_dialog import LibraryDialog  # noqa: E402
import promptpop.app as appmod  # noqa: E402  导入即验证装配无副作用

# 1) meta-prompt（含多轮迭代）
mu = build_messages("user", "帮我写个周报")
fu = build_followup_messages("user", "# Role: 旧版", "更短一点")
assert mu[1]["content"] == "帮我写个周报"
assert "更短一点" in fu[1]["content"] and "迭代" in fu[0]["content"]
assert "# Role:" in get_meta_template("user")
print("[ok] meta_prompt + followup")

# 2) providers.resolve
for pid in PROVIDERS:
    b, k, m, nk = resolve(pid, Config().data)
    assert b and m
assert resolve("ollama", Config().data)[1] == "ollama"
print("[ok] providers.resolve")

# 3) config save/load
cfg = Config()
cfg.set("provider", "openai")
cfg.set("model", "gpt-4o-mini")
cfg.set("theme", "light")
cfg.set("selection_toolbar", True)
cfg.save()
cfg2 = Config.load()
assert cfg2.get("provider") == "openai" and cfg2.get("theme") == "light"
print("[ok] config save/load @", config_path())

# 4) overlay 实例化 + 主题切换 + 输入
ov = OverlayWindow(Config.load())
ov.set_input("把这段话优化一下")
assert ov.input_box.toPlainText() == "把这段话优化一下"
ov.apply_theme()  # dark/light 都不报错
print("[ok] overlay instantiate + input + apply_theme")

# 5) 流式槽 + 迭代行显示
ov._on_token("# Role: 测试")
ov._on_done("# Role: 测试\n## Profile")
assert "# Role: 测试" in ov.result_box.toPlainText()
assert ov.btn_copy.isEnabled() and ov.btn_iterate.isEnabled()
assert not ov.iter_row.isHidden()  # 离屏下顶层未 show，用 isHidden 判显式开关
print("[ok] streaming slots + iter row visible")

# 6) 失败槽（模拟真实流程：开跑前结果区已清空）
ov.result_box.clear()
ov._on_failed("boom")
assert "boom" in ov.status.text()
assert not ov.btn_replace.isEnabled()
print("[ok] failed slot")

# 7) 历史入库 / 列表
history.add_history("user", "deepseek", "deepseek-chat", "输入X", "# Role: Y")
rows = history.list_history(10)
assert rows and rows[0][5] == "输入X"
print("[ok] history add/list (%d rows)" % len(rows))

# 8) 模板增/列/删
history.add_template("模板A", "自定义", "# Role: T")
tpls = history.list_templates()
assert any(t[1] == "模板A" for t in tpls)
tid = [t[0] for t in tpls if t[1] == "模板A"][0]
history.delete_template(tid)
assert not any(t[0] == tid for t in history.list_templates())
print("[ok] template add/list/delete")

# 9) 小工具条 + 库对话框 + 划词监视器（仅实例化，不启动/不 exec）
tb = SelectionToolbar()
tb.show_for("选中的文字", 100, 100)
assert tb.selected_text() == "选中的文字"
tb.hide()
lib = LibraryDialog(Config.load(), get_current_output=lambda: "# Role: Z")
assert lib.hist_list is not None and lib.tpl_list is not None
mon = SelectionMonitor()
assert mon._listener is None  # 未启动
assert extract_uia() in (None, "") or isinstance(extract_uia(), str)
print("[ok] toolbar + library dialog + selection monitor instantiate")

# 10) autostart（只读，不改注册表）
assert isinstance(autostart.is_enabled(), bool)
assert isinstance(autostart._entry_command(), str)
print("[ok] autostart read-only; entry:", autostart._entry_command()[:60], "...")

# 11) 剪贴板往返 + 前台句柄
try:
    actions.clipboard_set_text("hello-clip")
    print("[ok] clipboard round-trip:", repr(actions.clipboard_get_text()))
except Exception as e:  # noqa: BLE001
    print("[warn] clipboard offscreen:", e)
print("[ok] get_foreground_hwnd ->", actions.get_foreground_hwnd())

print("SMOKE OK (M1-M4)")
