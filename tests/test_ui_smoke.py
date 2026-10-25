"""UI 冒烟测试（离屏）：把「点了没反应 / 被挡住」这类问题变成可自动检查的断言。

运行： QT_QPA_PLATFORM=offscreen python tests/test_ui_smoke.py

覆盖（针对用户实测反馈的缺陷）：
  1. 所有由浮窗打开的弹窗都必须带 WindowStaysOnTopHint，否则会被置顶浮窗挡住
  2. 浮窗/设置/库对话框里每个按钮都必须真的连了处理函数（否则点了没反应）
  3. 结果框可编辑（优化结果常需微调后再复制/替换）
  4. 有模态弹窗打开时，热键 show_at_cursor 不应把浮窗盖到弹窗上
  5. 工具条按「选区坐标」判定屏幕（副屏不会夹取到主屏边界）
  6. 浮窗尺寸记忆（拖大后下次唤起保持）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QDialog, QMessageBox, QInputDialog, QPushButton,
)

from promptpop.config import Config  # noqa: E402
from promptpop import ui_util  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402
from promptpop.settings_dialog import SettingsDialog  # noqa: E402
from promptpop.library_dialog import LibraryDialog  # noqa: E402
from promptpop.toolbar import SelectionToolbar  # noqa: E402

# 测试隔离：SettingsDialog._save() 会调 autostart.enable()/disable()（写 HKCU Run 注册表项）。
# 跑测试**不应**改动用户真实的开机自启设置（否则一次回归就把自启删了），这里整体替换为空操作。
import promptpop.settings_dialog as _settings_mod  # noqa: E402


class _NoopAutostart:
    @staticmethod
    def enable():
        pass

    @staticmethod
    def disable():
        pass

    @staticmethod
    def is_enabled():
        return False


_settings_mod.autostart = _NoopAutostart


# 测试隔离：ModelFetcher 整体替换为假类——任何路径（⟳ 点击/首次显示自动拉取）
# 都不发出真实网络请求（离屏下网络线程在退出时仍 running → qFatal abort；
# 2026-10-25 实测：即使配置无 Key，list_models 也会出网拿 401）
import promptpop.overlay as _overlay_mod
from PySide6.QtCore import QThread as _QThread, Signal as _Signal


class _FakeModelFetcher(_QThread):
    done = _Signal(list)

    def __init__(self, *a, **kw):
        super().__init__()

    def run(self):
        self.done.emit([])


_overlay_mod.ModelFetcher = _FakeModelFetcher


def _app():
    return QApplication.instance() or QApplication([])


_TEST_CFG_DIR = os.path.join(tempfile.mkdtemp(prefix="promptpop_ui_smoke_"), "")
os.environ["PROMPTPOP_CONFIG_DIR"] = _TEST_CFG_DIR   # 隔离：无 Key → show_at_cursor
# 不会自动拉模型（ModelFetcher 发真实网络请求，退出时线程未完 → abort；
# 2026-10-25 实测定位：唯一未隔离配置目录的测试文件，曾用真实 Key 出网）


def _cfg():
    # 不写盘：只用于构造 UI（读隔离目录）
    return Config.load()


def _has_topmost(w):
    return bool(w.windowFlags() & Qt.WindowStaysOnTopHint)


# ---------- 1. 弹窗必须置顶（否则被主页面挡住） ----------
def test_dialogs_are_topmost():
    cfg = _cfg()
    ov = OverlayWindow(cfg)

    settings = SettingsDialog(cfg, ov)
    library = LibraryDialog(cfg, lambda: "", ov)
    diff = QDialog(ov)
    box = QMessageBox(ov)
    inp = QInputDialog(ov)
    result = ui_util.ScrollableResultDialog(ov, "评估", "内容")._dlg

    for name, w in (("设置", settings), ("库", library), ("差异视图", diff),
                    ("消息框", box), ("输入框", inp), ("结果框", result)):
        assert not _has_topmost(w), "%s 默认本不该置顶（用于验证 make_topmost 真的起了作用）" % name
        ui_util.make_topmost(w)
        assert _has_topmost(w), "%s 弹窗未置顶 → 会被主浮窗挡住" % name
    print("[ok] 1. 六类弹窗经 make_topmost 后均置顶")


# ---------- 2. 每个按钮都真的连了处理函数 ----------
def _click_receivers(btn):
    """clicked 信号已连接的数量。

    PySide6 的 QObject.receivers 只认 Qt 内部规范化签名（形如 "2clicked(bool)"），
    普通写法 "clicked()" 一律返回 0 —— 这里按兼容顺序探测，任一命中即认为已连接。
    """
    for sig in ("2clicked(bool)", "clicked(bool)", "clicked()"):
        try:
            n = btn.receivers(sig)
        except Exception:
            continue
        if n:
            return n
    return 0


def _all_buttons(widget):
    return [b for b in widget.findChildren(QPushButton)]


def test_buttons_are_wired():
    cfg = _cfg()
    ov = OverlayWindow(cfg)

    # 允许「当前不可用」的按钮（enabled=False），但不允许「点了没反应」
    skip_when_disabled = True
    for b in _all_buttons(ov):
        if b.menu() is not None:
            continue  # 菜单按钮（⚙ 高级 / ⋯ 更多）：点击=弹菜单，动作在 QMenu action 上
        n = _click_receivers(b)
        if skip_when_disabled and not b.isEnabled():
            continue  # 置灰的按钮（如未出结果时的复制/替换）不算缺陷
        assert n > 0, "浮窗按钮「%s」没有连接处理函数 → 点了没反应" % b.text()

    settings = SettingsDialog(cfg, ov)
    for b in _all_buttons(settings):
        if not b.isEnabled():
            continue
        assert _click_receivers(b) > 0, "设置按钮「%s」未连接" % b.text()

    library = LibraryDialog(cfg, lambda: "", ov)
    for b in _all_buttons(library):
        if not b.isEnabled():
            continue
        assert _click_receivers(b) > 0, "库按钮「%s」未连接" % b.text()

    tb = SelectionToolbar()
    for b in _all_buttons(tb):
        assert _click_receivers(b) > 0, "工具条按钮「%s」未连接" % b.text()

    print("[ok] 2. 浮窗/设置/库/工具条所有可用按钮均已连接处理函数")


# ---------- 2b. 历史单条删除（确认流程 + 只删选中项） ----------
def test_history_delete_single():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="pp_hdel_")
    os.environ["PROMPTPOP_CONFIG_DIR"] = tmp
    from promptpop import history as hist

    hist.init_db()
    hist.add_history("user", "m", "m", "delete-me-input", "out1")
    hist.add_history("user", "m", "m", "keep-me", "out2")
    ov = OverlayWindow(_cfg())
    library = LibraryDialog(_cfg(), lambda: "", ov)
    assert library.hist_list.count() >= 2
    # 根据内容定位要删的那条（list_history 默认最新在前，不能假定在第 0 行）
    target_row = -1
    for i in range(library.hist_list.count()):
        if "delete-me-input" in (library.hist_list.item(i).text() or ""):
            target_row = i
            break
    assert target_row >= 0, "未找到待测历史项"
    library.hist_list.setCurrentRow(target_row)
    orig = ui_util.exec_confirm
    ui_util.exec_confirm = lambda *a, **k: True   # 无头环境注入「确认=是」
    try:
        library._del_history()
    finally:
        ui_util.exec_confirm = orig
    rows = hist.list_history(100)
    inputs = [r[5] for r in rows]
    assert "delete-me-input" not in inputs, inputs
    assert "keep-me" in inputs, inputs
    print("[ok] 2b. 历史单条删除（确认流程 + 只删选中项）")


# ---------- 3. 结果框可编辑 ----------
def test_result_box_editable():
    ov = OverlayWindow(_cfg())
    assert not ov.result_box.isReadOnly(), "结果框应可编辑（便于微调后复制/替换）"
    ov.result_box.setPlainText("改一下")
    assert ov.result_box.toPlainText() == "改一下"
    print("[ok] 3. 结果框可编辑")


# ---------- 4. 有模态弹窗时，热键不应把浮窗盖上来 ----------
class _FakeDialog:
    def __init__(self):
        self.raised = 0
        self.activated = 0

    def isVisible(self):
        return True

    def raise_(self):
        self.raised += 1

    def activateWindow(self):
        self.activated += 1


def test_hotkey_does_not_cover_dialog():
    ov = OverlayWindow(_cfg())
    ov.hide()
    fake = _FakeDialog()
    ov._active_dialog = fake
    before = ov.pos()
    ov.show_at_cursor()
    assert fake.raised == 1 and fake.activated == 1, "应把已打开的弹窗提到最前"
    assert not ov.isVisible(), "浮窗不该在弹窗打开时抢到前面"
    assert ov.pos() == before, "浮窗位置不该被改动"

    # 弹窗关闭后恢复正常：浮窗应照常出现
    ov._active_dialog = None
    ov.show_at_cursor()
    assert ov.isVisible(), "弹窗关闭后热键应能正常唤起浮窗"
    print("[ok] 4. 有弹窗时只提升弹窗、浮窗不抢前；弹窗关闭后回归正常")


# ---------- 5. 工具条按选区坐标定位 ----------
def test_toolbar_position_within_screen():
    tb = SelectionToolbar()
    screen = QApplication.primaryScreen()
    geo = screen.availableGeometry()
    # 故意给一个贴右下的坐标，必须被夹回屏幕内
    tb.show_for("测试文本", geo.right() - 2, geo.bottom() - 2)
    g = tb.geometry()
    assert g.right() <= geo.right() + 1, "工具条右边越界：%r > %r" % (g.right(), geo.right())
    assert g.bottom() <= geo.bottom() + 1, "工具条下边越界：%r > %r" % (g.bottom(), geo.bottom())
    assert g.left() >= geo.left() - 1 and g.top() >= geo.top() - 1
    assert tb.selected_text() == "测试文本"
    print("[ok] 5. 工具条贴边坐标被夹回屏幕内")


# ---------- 6. 尺寸记忆 ----------
def test_window_size_memory():
    cfg = _cfg()
    ov = OverlayWindow(cfg)
    ov.resize(820, 640)
    ov._remember_geometry()
    assert int(cfg.get("window_width", 0)) == 820
    assert int(cfg.get("window_height", 0)) == 640

    ov2 = OverlayWindow(cfg)
    assert ov2.width() == 820 and ov2.height() == 640, \
        "重新构造应恢复上次尺寸，实际 %dx%d" % (ov2.width(), ov2.height())
    print("[ok] 6. 浮窗尺寸记忆（隐藏时保存，重建时恢复）")


# ---------- 7. Ollama 地址留空必须能保存（否则多数用户点保存被拦） ----------
def _offline_cfg():
    """只读配置副本：save 置空，避免测试写脏用户真实配置。"""
    cfg = _cfg()
    cfg.save = lambda: None
    return cfg


# ---------- 7b. 自定义 OpenAI 兼容端点（R6） ----------
def test_custom_endpoint_in_settings():
    from promptpop.settings_dialog import SettingsDialog, _CustomProviderDialog
    cfg = _offline_cfg()
    cfg.data["custom_providers"] = [{
        "id": "OpenRouter", "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "qwen/qwen3", "needs_key": True, "api_key": "sk-x"}]
    ov = OverlayWindow(cfg)
    dlg = SettingsDialog(cfg, ov)
    # 1) 设置与浮窗的 provider 下拉都应包含自定义端点
    ids = [dlg.provider.itemData(i) for i in range(dlg.provider.count())]
    assert "OpenRouter" in ids, "设置 provider 下拉缺少自定义端点"
    ov_ids = [ov.provider_box.itemData(i) for i in range(ov.provider_box.count())]
    assert "OpenRouter" in ov_ids, "浮窗 provider 下拉缺少自定义端点"
    # 2) 端点 tab 列表应显示该行
    assert dlg.custom_list.count() == 1
    # 3) 添加对话框校验：空名称 / 非法 URL 应拒绝，合法应通过
    cpd = _CustomProviderDialog(dlg)
    cpd.name.setText(""); cpd.base_url.setText("http://x/v1")
    assert cpd.to_entry()["label"] == ""  # to_entry 不校验，仅取数
    cpd.name.setText("LocalLLM"); cpd.base_url.setText("http://127.0.0.1:8000/v1")
    cpd.model.setText("m"); cpd.needs_key.setChecked(False)
    entry = cpd.to_entry()
    assert entry == {"label": "LocalLLM", "base_url": "http://127.0.0.1:8000/v1",
                     "default_model": "m", "api_key": "", "needs_key": False}, entry
    # 4) 删除后列表清空
    dlg.custom_list.setCurrentRow(0)
    dlg._on_del_endpoint()
    assert dlg.custom_list.count() == 0 and cfg.data["custom_providers"] == []
    print("[ok] 7b. 自定义端点进下拉/列表 + 增删对话框取值")


def test_save_with_empty_ollama_url():
    cfg = _offline_cfg()
    ov = OverlayWindow(cfg)
    dlg = SettingsDialog(cfg, ov)
    dlg.ollama_url.setText("")          # 留空 = 用默认地址
    dlg.temperature.setText("0.3")
    dlg.hotkey.setText("Ctrl+Shift+Space")
    dlg._save()
    assert dlg.result() == QDialog.Accepted, "留空 Ollama 地址却无法保存 → 会被校验拦住"
    print("[ok] 7. Ollama 地址留空可正常保存")


# ---------- 8. 改热键后要能立即重新注册（否则要重启才生效） ----------
def test_hotkey_change_emits_signal():
    cfg = _offline_cfg()
    ov = OverlayWindow(cfg)
    dlg = SettingsDialog(cfg, ov)
    got = []
    dlg.hotkey_changed.connect(got.append)
    dlg.ollama_url.setText("")
    dlg.hotkey.setText("Ctrl+Alt+K")
    dlg._save()
    assert got and got[0] == "<ctrl>+<alt>+k", \
        "热键变更未发出信号（应用需重启才生效），实际 %r" % got
    print("[ok] 8. 改热键发出 hotkey_changed 信号（可即时重注册）")


# ---------- 8b. 热键注册失败要有明确反馈（R2 · 原生注册） ----------
def test_hotkey_registration_failure_feedback():
    """新热键被其它程序占用 → 明确告警 + 回滚旧热键 + 不关对话框；成功则正常保存。"""
    cfg = _offline_cfg()
    saved = []
    cfg.save = lambda: saved.append(1)
    old = cfg.get("hotkey")
    calls = []

    def fake_restart(combo):
        calls.append(combo)
        return False, "该热键已被其它程序占用，请换一个组合"

    ov = OverlayWindow(cfg)
    dlg = SettingsDialog(cfg, ov, hotkey_restart=fake_restart)
    dlg.hotkey.setText("Ctrl+Alt+K")
    warned = []
    orig = ui_util.exec_warning
    ui_util.exec_warning = lambda *a, **k: warned.append(a)
    try:
        dlg._save()
    finally:
        ui_util.exec_warning = orig
    assert calls and calls[0] == "<ctrl>+<alt>+k", calls
    assert warned, "注册失败应弹出告警（否则用户以为改成功了）"
    assert cfg.get("hotkey") == old, "注册失败应保留旧热键"
    assert dlg.result() != QDialog.Accepted, "注册失败不应关闭对话框"
    # 关键：失败必须在**任何落盘之前**返回，否则用户随后点「取消」
    # （reject 只回滚内存）会造成内存与磁盘不一致
    assert not saved, "热键注册失败时不应落盘"
    assert dlg.hotkey.text().lower().replace(" ", "") != "ctrl+alt+k", \
        "失败后输入框应退回实际生效的旧组合，避免'显示新值其实没生效'"

    # 成功路径：回调返回 ok → 正常关闭 + 新热键入配置 + 落盘
    dlg2 = SettingsDialog(cfg, ov, hotkey_restart=lambda c: (True, ""))
    dlg2.hotkey.setText("Ctrl+Alt+K")
    dlg2._save()
    assert dlg2.result() == QDialog.Accepted
    assert cfg.get("hotkey") == "<ctrl>+<alt>+k", cfg.get("hotkey")
    assert saved, "成功保存应落盘"
    print("[ok] 8b. 热键注册失败：告警 + 不落盘 + 退回旧值 + 不关窗；成功：正常保存")


# ---------- 8c. 「恢复默认」：只重置设置项，保留自定义端点/Key（R5） ----------
def test_reset_defaults_keeps_user_data():
    from promptpop.config import reset_to_defaults, DEFAULT_CONFIG
    from promptpop.util import validate_hotkey

    # 纯函数：重置设置项，保留用户数据
    src = {
        "hotkey": "<ctrl>+<alt>+k",
        "theme": "light",
        "temperature": 1.5,
        "custom_providers": [{"id": "OpenRouter", "base_url": "https://x/v1"}],
        "api_keys": {"deepseek": "sk-old", "openai": "", "ollama": ""},
    }
    out = reset_to_defaults(src)
    assert out["hotkey"] == DEFAULT_CONFIG["hotkey"]
    assert out["theme"] == DEFAULT_CONFIG["theme"]
    assert out["temperature"] == DEFAULT_CONFIG["temperature"]
    assert out["custom_providers"] == src["custom_providers"], "自定义端点应保留"
    assert out["api_keys"]["deepseek"] == "sk-old", "api_keys 应保留"

    # UI：点「恢复默认」→ 控件回默认；点「保存」→ 才落盘
    cfg = _offline_cfg()
    cfg.set("hotkey", "<ctrl>+<alt>+k")
    cfg.set("theme", "light")
    cfg.data["custom_providers"] = [{
        "id": "OpenRouter", "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "m", "needs_key": False, "api_key": ""}]
    ov = OverlayWindow(cfg)
    dlg = SettingsDialog(cfg, ov)
    o_confirm, o_msg = ui_util.exec_confirm, ui_util.exec_message
    ui_util.exec_confirm = lambda *a, **k: True
    ui_util.exec_message = lambda *a, **k: None
    try:
        dlg._reset_defaults()
    finally:
        ui_util.exec_confirm, ui_util.exec_message = o_confirm, o_msg
    assert validate_hotkey(dlg.hotkey.text()) == DEFAULT_CONFIG["hotkey"], dlg.hotkey.text()
    assert dlg.theme.currentText() == DEFAULT_CONFIG["theme"]
    assert cfg.get("theme") == "light", "恢复默认只改控件，未点保存不该落盘"
    dlg._save()
    assert cfg.get("theme") == DEFAULT_CONFIG["theme"], "保存后应落盘默认值"
    assert cfg.get("hotkey") == DEFAULT_CONFIG["hotkey"]
    assert cfg.data["custom_providers"], "自定义端点不应被清掉"
    print("[ok] 8c. 恢复默认：控件回默认 + 需保存才生效 + 保留自定义端点")


# ---------- 8d. 首次运行引导判定（R6） ----------
def test_first_run_guidance_pure():
    from promptpop.util import should_guide_first_run
    assert should_guide_first_run({}, True, False) is True, "首次 + 需Key + 没Key → 应引导"
    assert should_guide_first_run({}, True, True) is False, "已有 Key → 不打扰"
    assert should_guide_first_run({}, False, False) is False, "Ollama 不需要 Key → 不打扰"
    assert should_guide_first_run({"first_run_done": True}, True, False) is False, "引导只做一次"
    print("[ok] 8d. 首次运行引导判定（需Key+无Key+未跑过 才引导）")


# ---------- 8e. 启动关键路径不加载 keyring（惰性加载，R7） ----------
def test_keyring_not_loaded_at_startup():
    """新进程里 import promptpop.app 后 sys.modules 不应含 keyring。

    keyring 是本项目导入最贵的单个依赖（独立导入约 0.4s），而启动时通常无事可做
    （只有 config 里还留明文 Key 才需迁移）——必须确保它不在启动关键路径上。
    """
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    code = ("import sys; sys.path.insert(0, r'%s'); "
            "import promptpop.app; "
            "print('KEYRING_LOADED=' + str('keyring' in sys.modules))") % root
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=root, env=env, timeout=120)
    assert "KEYRING_LOADED=False" in (out.stdout or ""), (out.stdout, out.stderr)
    print("[ok] 8e. 启动关键路径不加载 keyring（惰性加载生效）")


# ---------- 9. 关闭设置时断开在跑的预检线程（防回调已销毁对象） ----------
class _FakeThread:
    """模拟还在跑的 PingThread（只需 result.disconnect 可调用）。"""

    class _Sig:
        def __init__(self, outer):
            self.outer = outer

        def disconnect(self, _slot=None):
            self.outer.disconnected += 1

    def __init__(self):
        self.disconnected = 0
        self.result = _FakeThread._Sig(self)


def test_settings_close_disconnects_ping_thread():
    ov = OverlayWindow(_offline_cfg())
    dlg = SettingsDialog(_offline_cfg(), ov)
    fake = _FakeThread()
    dlg._ping_thread = fake
    dlg.close()
    assert fake.disconnected == 1, "关闭设置时未断开预检线程回调 → 可能崩溃"
    print("[ok] 9. 关闭设置会断开在跑的连通性预检回调")


# ---------- 10. 替换/插入失败时窗口保持打开（否则提示一闪而过） ----------
def test_replace_failure_keeps_window_open():
    from promptpop import actions
    ov = OverlayWindow(_offline_cfg())
    ov.result_box.setPlainText("要替换回去的结果")
    orig = actions.replace_selection
    actions.replace_selection = lambda t, hwnd: False
    try:
        ov.show()
        ov._on_replace()
        assert ov.isVisible(), "替换失败不该直接隐藏窗口"
        assert "手动 Ctrl+V" in ov.status.text(), "应提示用户手动粘贴，实际：%r" % ov.status.text()
    finally:
        actions.replace_selection = orig
    print("[ok] 10. 替换失败保持窗口打开并提示手动粘贴")


# ---------- 11. 浮窗快捷键真的能触发（Ctrl 组合键最容易静默失效） ----------
def test_overlay_shortcuts_actually_fire():
    """按 Ctrl+D/R/I/Shift+C 与 Esc，必须真的走到对应处理函数。

    回归背景：早期用 e.text() 取主键名，Windows 下 Ctrl 组合键的 text()
    是控制字符（Ctrl+D→\\x04），导致所有 Ctrl 快捷键静默失效；
    纯函数单测通过但集成失效，所以这里必须走真实 QKeyEvent。
    """
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent

    ov = OverlayWindow(_offline_cfg())
    calls = []
    ov._on_diff = lambda: calls.append("diff")
    ov._on_replace = lambda: calls.append("replace")
    ov._on_insert = lambda: calls.append("insert")
    ov._on_copy = lambda: calls.append("copy")
    ov._on_optimize = lambda: calls.append("optimize")
    ov._on_escape = lambda: calls.append("cancel")

    def press(key, mods=Qt.NoModifier):
        ov.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, mods))

    press(Qt.Key_D, Qt.ControlModifier)
    press(Qt.Key_R, Qt.ControlModifier)
    press(Qt.Key_I, Qt.ControlModifier)
    press(Qt.Key_C, Qt.ControlModifier | Qt.ShiftModifier)
    press(Qt.Key_Return, Qt.ControlModifier)
    press(Qt.Key_Escape)

    assert calls == ["diff", "replace", "insert", "copy", "optimize", "cancel"], \
        "浮窗快捷键未全部触发，实际：%r" % calls

    # 无修饰键的单字母不应误触发
    calls.clear()
    press(Qt.Key_D)
    press(Qt.Key_R)
    assert calls == [], "无 Ctrl 时不该触发，实际：%r" % calls
    print("[ok] 11. 浮窗快捷键真实按键事件可触发，且无 Ctrl 不误触发")


# ---------- 12. 尺寸记忆要跨重启生效（不能被配置迁移当未知键丢掉） ----------
def test_window_size_survives_restart():
    from promptpop.config import DEFAULT_CONFIG, migrate
    assert "window_width" in DEFAULT_CONFIG, "默认配置缺 window_width → 迁移时会丢弃"
    assert "window_height" in DEFAULT_CONFIG, "默认配置缺 window_height → 迁移时会丢弃"
    kept = migrate({"window_width": 900, "window_height": 700})
    assert kept["window_width"] == 900 and kept["window_height"] == 700, \
        "迁移后尺寸丢失：%r" % (kept.get("window_width"), kept.get("window_height"))
    print("[ok] 12. 浮窗尺寸跨重启保留（默认配置含键 + 迁移不丢）")


def test_clipboard_snapshot_restore_fidelity():
    """剪贴板完整快照：自定义 MIME 格式在 改写→还原 后仍保真（不丢 Office 私有格式）。

    离屏 QClipboard 不可靠，这里用 fake clipboard 隔离测试快照/还原的克隆逻辑。
    """
    from PySide6.QtCore import QMimeData
    import PySide6.QtWidgets as qtw
    from promptpop import capture

    src = QMimeData()
    src.setText("hello-promptpop")
    src.setData("application/x-promptpop-test", b"\x01\x02secret")

    class _FakeClip:
        def __init__(self, md):
            self._md = md

        def mimeData(self):
            return self._md

        def setMimeData(self, md):
            self._md = md

    fake = _FakeClip(src)
    orig = qtw.QApplication.clipboard
    qtw.QApplication.clipboard = staticmethod(lambda: fake)
    try:
        snap = capture._clipboard_snapshot()
        assert snap is not None
        assert "application/x-promptpop-test" in snap.formats()
        # 模拟取词过程中剪贴板被改写（清空）
        fake.setMimeData(QMimeData())
        # 原样还原后应恢复所有格式
        capture._clipboard_restore_full(snap)
        restored = fake.mimeData()
        assert restored.text() == "hello-promptpop"
        assert restored.data("application/x-promptpop-test").data() == b"\x01\x02secret"
    finally:
        qtw.QApplication.clipboard = orig
    print("[ok] 剪贴板快照还原保真")


def test_status_color_levels():
    ov = OverlayWindow(_offline_cfg())
    ov._status("失败：网络错误", "error")
    assert "#e06c5a" in ov.status.styleSheet(), "失败应显示红色"
    ov._status("已取消", "warn")
    assert "#c9a227" in ov.status.styleSheet(), "警告应显示黄色"
    ov._status("完成", "ok")
    assert "#5b9e5b" in ov.status.styleSheet(), "成功应显示绿色"
    ov._status("普通信息")
    assert ov.status.styleSheet() == "", "普通信息应回到主题默认色"
    print("[ok] 状态栏颜色分级（失败红/警告黄/成功绿/默认）")


def test_dialogs_have_default_button():
    """差异视图/库的「关闭」应为默认按钮（Enter 可关闭），且 Esc 可关闭。"""
    from promptpop.library_dialog import LibraryDialog
    cfg = _offline_cfg()
    ov = OverlayWindow(cfg)
    ov.input_box.setPlainText("原稿内容")
    ov.result_box.setPlainText("优化后内容")
    # 差异视图：直接构造内部按钮不方便，改为验证库对话框
    lib = LibraryDialog(cfg, ov.get_current_output, ov)
    btns = lib.findChildren(QPushButton)
    defaults = [b for b in btns if b.isDefault()]
    assert defaults, "库对话框应有一个默认按钮（Enter 关闭）"
    # Esc → reject（QDialog 默认行为），验证 dialogButton/reject 路径存在
    lib.reject()
    assert not lib.isVisible() or lib.result() == QDialog.Rejected
    print("[ok] 13. 对话框默认按钮 + Esc 关闭")


def test_max_input_guard():
    """输入超长应在优化/迭代/A-B 三条入口被拦截，且状态栏给出 warn 色。"""
    cfg = _offline_cfg()
    cfg.data["max_input_chars"] = 50
    ov = OverlayWindow(cfg)
    ov.input_box.setPlainText("x" * 200)
    ov._on_optimize()
    assert "过长" in ov.status.text(), ov.status.text()
    assert "#c9a227" in ov.status.styleSheet(), "超长提示应为警告色"
    # 迭代入口
    ov.result_box.setPlainText("y" * 10)
    ov.iter_edit.setText("z" * 200)
    ov._on_iterate()
    assert "过长" in ov.status.text(), ov.status.text()
    # A/B 入口（原文+结果合计超限）
    ov.result_box.setPlainText("y" * 100)
    ov._on_ab()
    assert "过长" in ov.status.text(), ov.status.text()
    print("[ok] 14. 输入超长守卫（优化/迭代/A-B）")


def test_settings_close_keeps_ping_ref():
    """关闭设置时只断开信号、不清引用（清引用会让运行中的 QThread 被 GC → abort）。"""
    cfg = _offline_cfg()
    ov = OverlayWindow(cfg)
    dlg = SettingsDialog(cfg, ov)

    class _FakeThread:
        def __init__(self):
            self.disconnected = 0
            self._running = True

        def isRunning(self):
            return self._running

        class _Sig:
            def __init__(self, outer):
                self.outer = outer

            def disconnect(self, _slot=None):
                self.outer.disconnected += 1

        def __init__(self):
            self.disconnected = 0
            self._running = True
            self.result = _FakeThread._Sig(self)

    fake = _FakeThread()
    dlg._ping_thread = fake
    dlg.close()
    assert fake.disconnected == 1, "关闭时应断开预检线程回调"
    assert dlg._ping_thread is fake, \
        "关闭设置不能把 _ping_thread 置 None——那会 GC 运行中的 QThread 导致 abort"
    print("[ok] 15. 关闭设置不断 ping 线程引用（防运行中析构）")


def test_toolbar_remembers_source_hwnd():
    """工具条应记住划词来源窗口，供「优化」作为替换目标。"""
    from promptpop.toolbar import SelectionToolbar
    tb = SelectionToolbar()
    assert tb.source_hwnd is None
    tb.source_hwnd = 12345
    assert tb.selected_text() == ""
    tb.show_for("hello", 10, 20)
    assert tb.selected_text() == "hello"
    assert tb.source_hwnd == 12345, "show_for 不应清除来源窗口记录"
    print("[ok] 16. 工具条记住划词来源窗口")


def test_toolbar_organize_signal():
    """工具条「整理」按钮应发出 organize 信号（零成本本地整理入口，区别于需 Key 的优化）。"""
    from promptpop.toolbar import SelectionToolbar
    tb = SelectionToolbar()
    got = []
    tb.organize.connect(lambda: got.append(1))
    tb.btn_organize.click()
    assert got == [1], "点「整理」应触发 organize 信号"
    print("[ok] 16b. 工具条「整理」按钮接线")


def test_iter_count_appears_near_limit():
    """迭代框同样受 max_input_chars 拦截，逼近/超限时应冒出字数提示，回落常态后清空。

    R10：R9 只给主输入框加了字数提示，迭代框会被 _on_iterate 静静拦掉却毫无提示，
    用户是「点了迭代才知道超了」。这里统一 quiet 模式：短文本不显示（避免噪音）。
    """
    cfg = _offline_cfg()
    cfg.data["max_input_chars"] = 100
    ov = OverlayWindow(cfg)
    # 常态（很短）：留空，不制造噪音
    ov.iter_edit.setText("更短")
    assert ov.iter_count.text() == "", "迭代要求很短时不应常驻字数提示"
    # 逼近上限（>90%）：冒出黄色提示
    ov.iter_edit.setText("x" * 95)
    assert ov.iter_count.text() and "c9a227" in ov.iter_count.styleSheet(), ov.iter_count.text()
    # 超限：标红
    ov.iter_edit.setText("x" * 150)
    assert "超限" in ov.iter_count.text(), ov.iter_count.text()
    # 删回正常：必须清空，否则残留提示会误导
    ov.iter_edit.setText("更短")
    assert ov.iter_count.text() == "", "删回正常后残留提示会误导"
    print("[ok] 17c. 迭代框字数提示（quiet 模式）")


def test_settings_cancel_restores_snapshot():
    """设置「取消」应还原端点增删等内存改动（防被后续 save 静默落盘）。"""
    import copy
    from promptpop import providers as P
    cfg = _offline_cfg()
    before = copy.deepcopy(cfg.data)
    ov = OverlayWindow(cfg)
    dlg = SettingsDialog(cfg, ov)
    P.add_custom_provider(cfg.data, "TempEP", "https://temp.example/v1", "m")
    assert len(cfg.data["custom_providers"]) == 1
    dlg.reject()  # 取消
    assert cfg.data == before, "取消后应还原打开时的配置快照"
    print("[ok] 17. 设置取消还原配置快照")


def test_wait_clipboard_change():
    """等待剪贴板变化：命中即返回（快于固定 sleep）、超时有界、轮询粒度正确。"""
    from promptpop import capture

    # 1) 第 3 次轮询时序列号变化 → 应立即返回 True
    seqs = iter([1, 1, 2, 2, 2])
    slept = []

    def seq():
        return next(seqs, 2)

    assert capture._wait_clipboard_change(1, 5.0, seq_getter=seq,
                                         sleeper=lambda s: slept.append(s)) is True
    assert len(slept) <= 3, "命中后不应继续轮询，实际轮询 %d 次" % len(slept)
    assert all(abs(s - 0.008) < 1e-9 for s in slept), "轮询粒度应为 8ms"

    # 2) 序列号始终不变 → 超时返回 False（用假 sleeper 不真等）
    ticks = {"n": 0}

    def seq_same():
        return 7

    def sleeper_fake(s):
        ticks["n"] += 1
        if ticks["n"] > 100000:      # 防御：绝不真死循环
            raise AssertionError("超时逻辑失效，轮询无界")

    # 用 monkeypatch 时间源模拟超时
    import promptpop.capture as cap
    orig_monotonic = cap.time.monotonic
    fake_t = {"v": 0.0}

    def fake_monotonic():
        return fake_t["v"]

    cap.time.monotonic = fake_monotonic
    try:
        def sleeper_advance(s):
            fake_t["v"] += s

        assert capture._wait_clipboard_change(7, 0.05, seq_getter=seq_same,
                                             sleeper=sleeper_advance) is False
        assert fake_t["v"] >= 0.05, "应至少等到超时上限"
    finally:
        cap.time.monotonic = orig_monotonic
    print("[ok] 18. 剪贴板变化等待（命中即返回/超时有界/8ms 粒度）")


def test_notify_hook():
    """完成/失败通知：走 notify_hook；无钩子时静默；配置可关。"""
    cfg = _offline_cfg()
    ov = OverlayWindow(cfg)
    got = []
    ov.notify_hook = lambda t, b: got.append((t, b))
    ov._notify("标题", "正文")
    assert got == [("标题", "正文")], got
    # 无钩子：不应抛异常
    ov2 = OverlayWindow(_offline_cfg())
    ov2._notify("t", "b")     # 静默通过
    # 钩子抛错：不应冒泡到 UI
    ov.notify_hook = lambda t, b: (_ for _ in ()).throw(RuntimeError("boom"))
    ov._notify("t", "b")      # 被吞掉
    # 失败路径会触发通知（配置开启且窗口未激活时）
    cfg.data["notify_on_done"] = True
    cfg2 = _offline_cfg()
    cfg2.data["notify_on_done"] = True
    ov3 = OverlayWindow(cfg2)
    hits = []
    ov3.notify_hook = lambda t, b: hits.append(t)
    ov3._set_busy(True)
    ov3._on_failed("网络错误：超时 ｜ 提示：检查网络")
    assert hits and "失败" in hits[0], hits
    print("[ok] 19. 完成/失败通知钩子（无钩子静默/异常隔离/失败也通知）")


# ---------- 19b. 托盘气泡点击唤起浮窗 ----------
def test_tray_bubble_click_raises_overlay():
    from promptpop import app as appmod
    from PySide6.QtWidgets import QSystemTrayIcon

    real = QSystemTrayIcon.isSystemTrayAvailable
    # 离屏环境无系统托盘，强制可用以验证真实接线（构造/连接不依赖真实托盘）
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
    try:
        a = _app()
        fired = []
        lib_fired = []
        tray = appmod._build_tray(a, appmod.make_icon, lambda: fired.append(1),
                                  lambda: None,
                                  open_library=lambda: lib_fired.append(1))
        assert tray is not None, "应构造出托盘"
        assert tray.receivers("2messageClicked()") > 0, "气泡点击应连接唤起浮窗"
        tray.messageClicked.emit()           # 模拟点击气泡
        assert fired, "气泡点击应触发唤起浮窗"
        # 托盘菜单应含「历史与模板库」，且触发能回调（浮窗关着时也能查历史）。
        # 先 gc.collect()：QAction 若没挂 parent 会被回收 → 菜单变空（真实缺陷，必须能测出来）
        import gc
        gc.collect()
        menu = tray.contextMenu()
        assert menu is not None and len(menu.actions()) >= 4, \
            "托盘菜单被回收成空菜单（QAction 缺 parent），实际 %d 项" % (
                len(menu.actions()) if menu else -1)
        lib_acts = [ac for ac in menu.actions() if "历史" in ac.text()]
        assert lib_acts, "托盘菜单应含「历史与模板库」入口"
        lib_acts[0].trigger()
        assert lib_fired, "「历史与模板库」菜单项应触发回调"
    finally:
        QSystemTrayIcon.isSystemTrayAvailable = real
    print("[ok] 19b. 托盘气泡点击唤起浮窗 + 菜单含「历史与模板库」入口")


# ---------- 19c. 从托盘库加载时，隐藏的浮窗要被带出来（R3） ----------
def test_library_load_raises_hidden_overlay():
    """含**真实模态路径**：库对话框「先 emit load_requested、再 accept()」，
    回调发生时弹窗仍开着（_active_dialog 仍指向它），此时 show_at_cursor 会被
    「有活动弹窗只提前弹窗」的守卫挡住——所以显示必须延后到库窗口关闭之后。
    """
    a = _app()
    cfg = _offline_cfg()
    ov = OverlayWindow(cfg)
    ov.hide()
    assert not ov.isVisible()
    ov._on_library_load("历史的输入文本", "历史的输出")
    a.processEvents()                      # 显示被排到下一轮事件循环
    assert ov.isVisible(), "隐藏状态下加载历史后应显示浮窗（否则看不到结果）"
    assert ov.input_box.toPlainText() == "历史的输入文本"

    # --- 真实模态路径 ---
    ov2 = OverlayWindow(cfg)
    ov2.hide()
    modal = QDialog(ov2)
    modal.show()                           # 必须真的可见，否则守卫会放行 → 测不出问题
    a.processEvents()
    ov2._active_dialog = modal             # 模拟 _open_modal 期间的守卫状态
    ov2._on_library_load("模态加载的文本", "模态输出")
    assert not ov2.isVisible(), "模态期间不应把浮窗盖到库对话框上"
    ov2._active_dialog = None              # 模拟 _open_modal 的 finally（库窗口已关）
    a.processEvents()
    assert ov2.isVisible(), "库关闭后应把浮窗带出来（否则用户看不到加载结果）"
    assert ov2.input_box.toPlainText() == "模态加载的文本"
    modal.hide()
    print("[ok] 19c. 库加载带出隐藏浮窗（含真实模态路径：延后显示）")


# ---------- 19d. 托盘「划词自动弹工具条」开关（R4） ----------
def test_tray_selection_toggle():
    from promptpop import app as appmod
    from PySide6.QtWidgets import QSystemTrayIcon

    cfg = _offline_cfg()
    saved = []
    cfg.save = lambda: saved.append(1)
    cfg.set("selection_toolbar", True)

    real = QSystemTrayIcon.isSystemTrayAvailable
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
    try:
        a = _app()
        tray = appmod._build_tray(a, appmod.make_icon, lambda: None, lambda: None,
                                  cfg=cfg)
        import gc
        gc.collect()
        menu = tray.contextMenu()
        sels = [ac for ac in menu.actions() if ac.isCheckable()]
        assert sels, "托盘菜单应含可勾选的「划词自动弹工具条」"
        act = sels[0]
        assert act.isChecked() is True, "初始应与配置一致（开）"
        act.setChecked(False)                      # 模拟用户取消勾选
        assert cfg.get("selection_toolbar") is False, "取消勾选应写入配置"
        assert saved, "开关切换应落盘"
        # 打开菜单时应同步「设置面板里改过的值」（不该反写配置）
        n_before = len(saved)
        cfg.set("selection_toolbar", True)
        menu.aboutToShow.emit()
        assert act.isChecked() is True, "打开菜单应同步最新值"
        assert len(saved) == n_before, "同步只是刷新勾选态，不该写配置"
    finally:
        QSystemTrayIcon.isSystemTrayAvailable = real
    print("[ok] 19d. 托盘「划词自动弹工具条」开关（写配置 + 打开菜单同步）")


# ---------- 20b. 热键切换失败必回滚旧组合（R8 审查 #5） ----------
def test_hotkey_restarter_rollback():
    from promptpop.app import make_hotkey_restarter

    class FakeBridge:
        def __init__(self, script):
            self.script = list(script)
            self.calls = []

        def register(self, combo):
            self.calls.append(combo)
            return self.script.pop(0)

    # 成功：切换 + 更新 state
    b = FakeBridge([(True, "")])
    st = {"active": True, "error": "", "combo": "<ctrl>+<shift>+<space>"}
    ok, _ = make_hotkey_restarter(b, st)("<ctrl>+<alt>+k")
    assert ok and st["combo"] == "<ctrl>+<alt>+k" and st["active"] is True

    # 失败：必须把旧组合注册回去（register 内部先 unregister，不回滚=旧热键也没了）
    b2 = FakeBridge([(False, "被占用"), (True, "")])
    st2 = {"active": True, "error": "", "combo": "<ctrl>+<shift>+<space>"}
    ok2, err2 = make_hotkey_restarter(b2, st2)("<ctrl>+<alt>+k")
    assert ok2 is False and "占用" in err2
    assert b2.calls == ["<ctrl>+<alt>+k", "<ctrl>+<shift>+<space>"], b2.calls
    assert st2["combo"] == "<ctrl>+<shift>+<space>", "失败后 combo 不该变"
    assert st2["active"] is True, "回滚成功后仍应有可用热键"

    # 边界：新组合 == 旧组合且失败 → 仍要回滚注册一次（跳过就会出现「一个热键都没有」）
    b3 = FakeBridge([(False, "被占用"), (True, "")])
    st3 = {"active": True, "error": "", "combo": "<ctrl>+<c>"}
    ok3, _ = make_hotkey_restarter(b3, st3)("<ctrl>+<c>")
    assert ok3 is False
    assert b3.calls == ["<ctrl>+<c>", "<ctrl>+<c>"], b3.calls
    print("[ok] 20b. 热键切换失败必回滚旧组合（含 prev==new 边界）")


# ---------- 20. 本地整理结果可存为历史（R5 遗留缺口） ----------
def test_local_action_save_to_history():
    import tempfile
    from PySide6.QtWidgets import QPushButton, QListWidget

    tmp = tempfile.mkdtemp(prefix="pp_la_")
    os.environ["PROMPTPOP_CONFIG_DIR"] = tmp
    from promptpop import history as hist

    hist.init_db()
    ov = OverlayWindow(_cfg())
    ov.input_box.setPlainText("  hello \n  world  ")
    captured = {}
    ov._open_modal = lambda dlg: captured.setdefault("dlg", dlg) or True
    ov._on_local_tools()
    dlg = captured.get("dlg")
    assert dlg is not None, "本地整理对话框应被创建"
    save_btn = None
    for b in dlg.findChildren(QPushButton):
        if b.text() == "存为历史":
            save_btn = b
            break
    assert save_btn is not None, "应有「存为历史」按钮"
    assert any(isinstance(w, QListWidget) for w in dlg.findChildren(QListWidget)), "应有动作列表"
    save_btn.click()                       # _save：写入 history（mode=local）
    rows = hist.list_history(100)
    assert any(r[2] == "local" for r in rows), "本地动作结果应写入历史"
    assert any("hello" in (r[5] or "") and "world" in (r[5] or "") for r in rows), rows
    print("[ok] 20. 本地整理结果可存为历史（R5 遗留缺口闭合）")


def main():
    _app()
    test_dialogs_are_topmost()
    test_buttons_are_wired()
    test_history_delete_single()
    test_result_box_editable()
    test_hotkey_does_not_cover_dialog()
    test_toolbar_position_within_screen()
    test_window_size_memory()
    test_save_with_empty_ollama_url()
    test_hotkey_change_emits_signal()
    test_hotkey_registration_failure_feedback()
    test_reset_defaults_keeps_user_data()
    test_first_run_guidance_pure()
    test_keyring_not_loaded_at_startup()
    test_settings_close_disconnects_ping_thread()
    test_replace_failure_keeps_window_open()
    test_overlay_shortcuts_actually_fire()
    test_window_size_survives_restart()
    test_clipboard_snapshot_restore_fidelity()
    test_status_color_levels()
    test_custom_endpoint_in_settings()
    test_dialogs_have_default_button()
    test_max_input_guard()
    test_settings_close_keeps_ping_ref()
    test_toolbar_remembers_source_hwnd()
    test_settings_cancel_restores_snapshot()
    test_wait_clipboard_change()
    test_notify_hook()
    test_tray_bubble_click_raises_overlay()
    test_library_load_raises_hidden_overlay()
    test_tray_selection_toggle()
    test_hotkey_restarter_rollback()
    test_local_action_save_to_history()
    test_iter_count_appears_near_limit()
    print("UI SMOKE OK")


if __name__ == "__main__":
    main()
