"""应用装配：QApplication + 全局热键 + 划词监听 + 小工具条 + 托盘 + 浮窗。"""
import sys
import time
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QTimer
from .config import Config
from .overlay import OverlayWindow
from .settings_dialog import SettingsDialog
from .toolbar import SelectionToolbar
from .capture import SelectionMonitor
from . import actions, capture, autostart, secrets, single_instance, debuglog, history, util, ui_util, hotkey


def build_settings_opener(cfg, overlay, restart_hotkey):
    """统一的「打开设置」入口：置顶显示 + 热键改动后立即重新注册。

    restart_hotkey(new_combo) -> (ok, err)：由调用方提供；对话框据返回值
    决定是否提示「热键被占用」并保留原组合。
    重复打开守卫：设置面板已开着时（托盘/浮窗/气泡多入口连点）只提前，不叠开。
    """
    def open_settings():
        active = getattr(overlay, "_active_dialog", None)
        if active is not None and active.windowTitle() == "PromptPop 设置":
            try:
                if active.isVisible():
                    active.raise_()
                    active.activateWindow()
                    return
            except RuntimeError:   # 已被销毁
                overlay._active_dialog = None
        dlg = SettingsDialog(cfg, overlay, hotkey_restart=restart_hotkey)
        overlay._active_dialog = dlg
        try:
            ok = ui_util.exec_dialog(dlg)   # 必须置顶，否则被常驻最前的浮窗挡住
        finally:
            overlay._active_dialog = None
        if ok:
            overlay._sync_from_config()
            overlay.apply_theme()
    return open_settings


def make_hotkey_restarter(bridge, state):
    """构造「改热键立刻生效」的回调（抽成模块函数以便单测）。

    bridge.register(combo) -> (ok, err)；state 为 {"active","error","combo"} 字典。
    关键语义：**新组合失败时无条件把旧组合注册回去**——`bridge.register()` 内部会先
    unregister，若不回滚，旧热键也会一并消失（用户从「有一个能用的热键」变成「一个都没有」）。
    返回 (ok, err) 供设置对话框提示。
    """
    def restart_hotkey(new_combo):
        prev = state.get("combo")
        ok, err = bridge.register(new_combo)
        if not ok and prev:
            back_ok, _back_err = bridge.register(prev)
            state["active"] = back_ok
            state["error"] = err
            return ok, err
        state["active"] = ok
        state["error"] = err
        if ok:
            state["combo"] = new_combo
        return ok, err
    return restart_hotkey


def make_icon(size=64):
    """程序化绘制托盘/窗口图标（无图标文件依赖）。"""
    from PySide6.QtGui import QPixmap, QPainter, QColor, QIcon, QFont
    from PySide6.QtCore import Qt
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(192, 67, 58))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, size - 8, size - 8, 12, 12)
    p.setPen(QColor(255, 255, 255))
    p.setFont(QFont("Arial", int(size * 0.5), QFont.Bold))
    p.drawText(pm.rect(), Qt.AlignCenter, "P")
    p.end()
    return QIcon(pm)


def apply_high_dpi_policy():
    """高 DPI 适配（须在 QApplication 实例化前调用）。

    PassThrough 保留精确缩放因子，避免 125%/150% 屏上界面过大或模糊；
    AA_UseHighDpiPixmaps 让图标按设备像素比加载高分辨率资源。
    返回实际生效的取整策略名（便于测试断言）。
    """
    policy = Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    QApplication.setHighDpiScaleFactorRoundingPolicy(policy)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    return QApplication.highDpiScaleFactorRoundingPolicy()


def _show_about():
    """托盘「关于」：版本 + 配置/日志目录（排障时用户常不知道这些东西在哪）。"""
    from PySide6.QtWidgets import QApplication
    from . import __version__
    from .config import config_dir
    app = QApplication.instance()
    if app is None:
        return
    ui_util.exec_message(
        None, "关于 PromptPop",
        "PromptPop 划词提示词优化器\n版本：%s\n\n"
        "配置 / 日志 / 历史库目录：\n%s" % (__version__, config_dir()))


def _build_tray(app, make_icon, hotkey_show, open_settings, open_library=None,
                cfg=None):
    """构造系统托盘（菜单 + 气泡点击唤起浮窗）。抽出来便于测试。

    cfg 提供时，菜单里多一个「划词自动弹工具条」开关——写文本时经常嫌它打断，
    不必为此打开设置面板。返回 QSystemTrayIcon；无系统托盘（离屏测试）安全返回 None。
    """
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon()
    menu = QMenu()
    # 注意：QAction 必须挂 parent=menu。否则 action 只被 Python 局部变量引用，
    # 函数返回后随引用计数归零被回收 → 托盘右键菜单变成**空菜单**（点了没反应）。
    act_show = QAction("显示（热键）", menu)
    act_show.triggered.connect(hotkey_show)
    act_library = QAction("历史与模板库", menu)
    if open_library is not None:
        act_library.triggered.connect(open_library)

    act_sel = QAction("划词自动弹工具条", menu)
    act_sel.setCheckable(True)
    if cfg is not None:
        act_sel.setChecked(bool(cfg.get("selection_toolbar", True)))

        def _toggle_sel(checked):
            cfg.set("selection_toolbar", bool(checked))
            try:
                cfg.save()
            except Exception:
                pass
            try:
                tray.showMessage(
                    "PromptPop",
                    "划词工具条已%s" % ("启用" if checked else "暂停"),
                    msecs=2000)
            except Exception:
                pass

        act_sel.toggled.connect(_toggle_sel)

        def _sync_sel():
            # 打开菜单时同步（设置面板里可能刚改过），阻塞信号避免误触发写入
            act_sel.blockSignals(True)
            act_sel.setChecked(bool(cfg.get("selection_toolbar", True)))
            act_sel.blockSignals(False)

        menu.aboutToShow.connect(_sync_sel)

    act_settings = QAction("设置", menu)
    act_settings.triggered.connect(open_settings)
    act_about = QAction("关于 PromptPop", menu)
    act_about.triggered.connect(_show_about)
    act_quit = QAction("退出", menu)
    act_quit.triggered.connect(app.quit)
    menu.addAction(act_show)
    menu.addAction(act_library)
    menu.addAction(act_sel)
    menu.addAction(act_settings)
    menu.addAction(act_about)
    menu.addSeparator()
    menu.addAction(act_quit)
    tray.setIcon(make_icon())
    tray.setContextMenu(menu)
    tray.setToolTip("PromptPop 划词提示词优化器")
    tray.show()
    # 点击气泡即唤起浮窗（完成/失败时用户常已切到别处，一键回来）
    tray.messageClicked.connect(hotkey_show)
    return tray


def _make_notify(tray):
    """完成/失败通知：优先托盘气泡（无依赖、可降级）。气泡时长 3s。"""

    def _notify(title, body):
        try:
            tray.showMessage(title, body, msecs=3000)
        except Exception:
            pass

    return _notify


def main():
    apply_high_dpi_policy()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    _lock, ok = single_instance.acquire()
    if not ok:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, "PromptPop", "PromptPop 已在运行中（可从托盘唤起）。")
        return
    setattr(app, "_pp_singleton_lock", _lock)  # 防 GC 释放锁
    cfg = Config.load()
    try:
        # 只有 config 里真的还留着明文 Key 才做迁移——否则别为一次「无事可做」的迁移
        # 在启动关键路径上加载 keyring（~275ms，见 secrets 模块注释）
        if any((cfg.get("api_keys") or {}).values()):
            moved = secrets.migrate_plaintext_to_keyring(cfg)
            if moved:
                print("[secrets] 已将 %d 个明文 Key 迁移到系统钥匙串" % moved)
    except Exception as e:  # noqa: BLE001
        print("[secrets] migrate failed:", e)
    debuglog.configure(bool(cfg.get("debug_log")))
    try:
        pruned = history.prune_history(util.safe_int(cfg.get("history_retention_days"), 0))
        if pruned:
            debuglog.get_logger().info("pruned %d old history rows", pruned)
    except Exception as e:  # noqa: BLE001
        print("[history] prune failed:", e)
    overlay = OverlayWindow(cfg)
    overlay.apply_theme()
    overlay.setWindowIcon(make_icon())
    bridge = hotkey.create_hotkey_manager()
    toolbar = SelectionToolbar()
    toolbar.set_theme(cfg.get("theme"))   # 启动即跟随配置主题（否则 light 用户先见暗条）

    def _pick_owner_hwnd():
        """取前台窗口作为替换/插入目标，但排除浮窗与工具条自身。

        否则浮窗已聚焦时再按热键 / 点托盘「显示」，会把浮窗自己记成
        owner_hwnd，导致点「替换」把结果粘进自己的输入框。
        """
        fg = actions.get_foreground_hwnd()
        own = {int(overlay.winId()), int(toolbar.winId())}
        if fg and int(fg) in own:
            return overlay.owner_hwnd  # 保留上一次记录的真实来源
        return fg

    def open_overlay(prefill=""):
        overlay.owner_hwnd = _pick_owner_hwnd()
        if prefill and not overlay.input_box.toPlainText().strip():
            overlay.set_input(prefill)
        overlay.show_at_cursor()
        overlay.activateWindow()
        overlay.input_box.setFocus()

    def hotkey_show():
        open_overlay(capture.prefill_from_clipboard())

    bridge.activated.connect(hotkey_show)
    # 回退值必须是「规范格式」，否则会被 hotkey.parse_combo 判为非法（等于热键完全不注册）
    hk = util.validate_hotkey(cfg.get("hotkey")) or "<ctrl>+<shift>+<space>"
    hk_ok, hk_err = bridge.register(hk)
    hotkey_state = {"active": hk_ok, "error": hk_err, "combo": hk}
    if not hk_ok:
        print("[hotkey] 全局热键注册失败：", hk_err)

    restart_hotkey = make_hotkey_restarter(bridge, hotkey_state)

    app.aboutToQuit.connect(bridge.dispose)   # 注销热键 + 摘掉事件过滤器

    # 托盘与浮窗上的「设置」都走这一个入口
    _open_settings_base = build_settings_opener(cfg, overlay, restart_hotkey)

    def open_settings():
        _open_settings_base()
        toolbar.set_theme(cfg.get("theme"))   # 主题可能已切换，工具条同步

    overlay.open_settings_hook = open_settings

    # 划词监听（设置里可实时开关）
    monitor = SelectionMonitor(enabled_getter=lambda: bool(cfg.get("selection_toolbar", True)))

    def on_selection(x, y, program):
        if not cfg.get("selection_toolbar", True):
            return
        # 短窗口去重：连续在同一处拖选时，避免重复取词叠加主线程冻结
        now = time.time()
        last = getattr(on_selection, "_last", None)
        if last and last[0] == (x, y) and (now - last[1]) < 0.3:
            return
        on_selection._last = ((x, y), now)
        # 文件管理器/特定程序里「拖拽」多为移动文件而非选字，跳过避免误触发
        if not capture.should_capture_selection(program,
                                               cfg.data.get("selection_exclude_programs", [])):
            return
        # 排除在自己的浮窗/工具条里划词，避免自我触发（否则在输入框里选字也会弹工具条）
        fg = actions.get_foreground_hwnd()
        if fg and int(fg) in {int(overlay.winId()), int(toolbar.winId())}:
            return
        # 记住划词来源窗口：稍后点工具条「优化」时，浮窗已抢焦点，
        # 再取前台窗口会拿到浮窗自己 → 替换目标错误。此时存下的最可靠。
        toolbar.source_hwnd = fg
        text, _method = capture.extract_selected_text(cfg.data, program)  # 主线程取词
        if text and text.strip():
            toolbar.show_for(text.strip(), x, y)

    monitor.selection_made.connect(on_selection)
    monitor.start()

    def toolbar_optimize():
        t = toolbar.selected_text()
        toolbar.hide()
        # 优先用划词时记下的来源窗口；取不到再退回「当前前台（排除自身）」
        src = getattr(toolbar, "source_hwnd", None)
        overlay.owner_hwnd = src if src else _pick_owner_hwnd()
        # 一键直达：预填 + 显示 + 自动开始优化（省在浮窗再点一次）
        overlay.quick_optimize(t)

    def toolbar_copy():
        t = toolbar.selected_text()
        if t:
            actions.clipboard_set_text(t)
        toolbar.hide()

    def toolbar_organize():
        """工具条「整理」：零成本本地文本整理（无需 API Key）。

        预填选中文本到浮窗 → 打开本地整理面板，用户选动作后结果写入结果框。
        区别于「优化」（需 Key 调 LLM）。
        """
        t = toolbar.selected_text()
        toolbar.hide()
        src = getattr(toolbar, "source_hwnd", None)
        overlay.owner_hwnd = src if src else _pick_owner_hwnd()
        overlay.set_input(t)
        overlay.show_at_cursor()
        overlay.activateWindow()
        overlay.input_box.setFocus()
        overlay._on_local_tools()

    toolbar.optimize.connect(toolbar_optimize)
    toolbar.copy.connect(toolbar_copy)
    toolbar.organize.connect(toolbar_organize)

    # 开机自启：配置开则确保注册表项在
    if cfg.get("autostart") and not autostart.is_enabled():
        autostart.enable()

    if QSystemTrayIcon.isSystemTrayAvailable():
        # 托盘也提供「历史与模板库」入口 + 划词开关：否则浮窗关着时无法直接查/切
        tray = _build_tray(app, make_icon, hotkey_show, open_settings,
                           open_library=overlay._on_open_library, cfg=cfg)
        overlay.notify_hook = _make_notify(tray)

    combo = cfg.get("hotkey") or "<ctrl>+<shift>+<space>"
    if hotkey_state["active"]:
        overlay._status("就绪 · 热键 %s 唤起；划词也会弹工具条" % util.format_hotkey(combo))
    else:
        overlay._status("⚠ 全局热键注册失败（%s）；请用托盘菜单「显示」唤起，划词工具条仍可用"
                        % (hotkey_state.get("error") or "被系统/安全软件拦截"))
    # 首次运行引导：没配 Key 时「优化」必然失败，主动把设置面板带到面前（一次性）。
    # 老用户/已配 Key/用本地 Ollama 都不会被打扰（见 util.should_guide_first_run）。
    try:
        from .providers import resolve as _resolve_provider
        _pid = cfg.get("provider")
        _base, _pkey, _pmodel, _needs_key = _resolve_provider(_pid, cfg.data)
        _has_key = bool(secrets.resolve_api_key(cfg.data, _pid) or _pkey)
        _guide = util.should_guide_first_run(cfg.data, _needs_key, _has_key)
    except Exception as e:  # noqa: BLE001
        print("[first-run] guide check failed:", e)
        _guide = False
    if not cfg.get("first_run_done"):
        cfg.set("first_run_done", True)
        try:
            cfg.save()
        except Exception:
            pass
    if _guide:
        overlay._status("首次使用：请在「设置」里填入 API Key（或切到「Ollama 本地」免 Key；"
                        "也可先用「本地整理」零成本体验）", "warn")
        QTimer.singleShot(800, open_settings)

    overlay.show_at_cursor()
    sys.exit(app.exec())
