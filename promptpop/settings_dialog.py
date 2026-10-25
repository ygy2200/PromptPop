"""设置对话框：基本（provider/模型/Key/主题/温度/划词/自启）+ 优化模板。"""
from PySide6.QtCore import QThread, Signal as _QtSignal, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QDialogButtonBox, QLabel, QCheckBox, QPlainTextEdit, QTabWidget, QWidget,
    QMessageBox, QPushButton, QHBoxLayout, QListWidget, QListWidgetItem,
    QFileDialog,
)
from .providers import (PROVIDERS, resolve, get_all_providers,
                        add_custom_provider, remove_custom_provider)
from . import secrets
from . import autostart
from . import ui_util
from . import threads


class PingThread(QThread):
    """异步连通性预检，避免点「测试连接」时卡住界面。"""
    result = _QtSignal(bool, str)

    def __init__(self, base_url, proxy="", timeout=5.0):
        super().__init__()
        self.base_url = base_url
        self.proxy = proxy
        self.timeout = timeout

    def run(self):
        try:
            from .engine import ping
            ok = ping(self.base_url, timeout=self.timeout, proxy=self.proxy)
            self.result.emit(bool(ok), self.base_url or "")
        except Exception as e:  # noqa: BLE001
            self.result.emit(False, str(e))


class SettingsDialog(QDialog):
    """hotkey_changed：保存后若热键变了，由 app 侧重新注册全局热键（否则要重启才生效）。"""
    hotkey_changed = _QtSignal(str)

    def __init__(self, config, parent=None, hotkey_restart=None):
        super().__init__(parent)
        self.config = config
        # hotkey_restart(combo) -> (ok, err)：由 app 侧注入，用于「改热键即时注册」，
        # 并把注册失败原因（如被其它程序占用）带回对话框展示。
        # 为 None 时退回 hotkey_changed 信号（兼容旧路径/测试）。
        self.hotkey_restart = hotkey_restart
        self._ping_thread = None
        # 打开时快照配置：自定义端点的增删是直接改 config.data 的，
        # 若用户点「取消」，必须还原快照，否则内存里的改动会被后续任意一次
        # config.save()（浮窗换提供商/隐藏浮窗）静默落盘——等于取消不生效。
        import copy as _copy
        self._cfg_snapshot = _copy.deepcopy(config.data)
        self.setWindowTitle("PromptPop 设置")
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._basic_tab(), "基本")
        tabs.addTab(self._endpoints_tab(), "自定义端点")
        tabs.addTab(self._meta_tab(), "优化模板")
        tabs.addTab(self._backup_tab(), "备份与迁移")
        root.addWidget(tabs)

        note = QLabel("Key 仅存本地配置文件；优化请求直连你所选提供商，不经中转服务器。")
        note.setWordWrap(True)
        root.addWidget(note)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        b_reset = QPushButton("恢复默认")
        b_reset.setToolTip("把设置项恢复为默认值（自定义端点与已保存的 Key 不受影响）")
        b_reset.clicked.connect(self._reset_defaults)
        btns.addButton(b_reset, QDialogButtonBox.ResetRole)
        root.addWidget(btns)

    def _basic_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        self.provider = QComboBox()
        for pid, p in get_all_providers(self.config.data).items():
            self.provider.addItem(p["label"], pid)
        self.provider.setCurrentIndex(self.provider.findData(self.config.get("provider")))

        self.model = QLineEdit(self.config.get("model") or "")
        self._key_cleared = set()

        def _clear_key(edit, provider):
            """删除系统钥匙串里已保存的 Key（此前「留空=不修改」，无法清除）。"""
            if not ui_util.exec_confirm(
                    self, "清除 API Key",
                    "确定清除已保存的 %s API Key？\n下次使用需重新填写。" % provider):
                return
            if secrets.set_key(provider, ""):
                edit.clear()
                edit.setPlaceholderText("已清除（保存设置后生效）")
                self._key_cleared.add(provider)
            else:
                ui_util.exec_warning(self, "清除失败",
                                     "无法访问系统钥匙串，请重试或检查凭据管理器。")

        def _key_row(edit, provider):
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            b_clear = QPushButton("清除")
            b_clear.setFixedWidth(52)
            b_clear.setToolTip("删除系统钥匙串中已保存的 Key（输入框留空 = 不修改）")
            b_clear.clicked.connect(lambda: _clear_key(edit, provider))
            row.addWidget(b_clear)
            return row

        self.key_deepseek = QLineEdit()
        self.key_deepseek.setEchoMode(QLineEdit.Password)
        if secrets.has_key("deepseek"):
            self.key_deepseek.setPlaceholderText("已保存到系统钥匙串（留空则不修改）")
        self.key_openai = QLineEdit()
        self.key_openai.setEchoMode(QLineEdit.Password)
        if secrets.has_key("openai"):
            self.key_openai.setPlaceholderText("已保存到系统钥匙串（留空则不修改）")
        self.ollama_url = QLineEdit(self.config.get("ollama_base_url") or "")
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        self.theme.setCurrentText(self.config.get("theme") or "dark")
        self.temperature = QLineEdit(str(self.config.get("temperature", 0.3)))
        self.sel_toolbar = QCheckBox("选中文字后弹出小工具条（划词即优化）")
        self.sel_toolbar.setChecked(bool(self.config.get("selection_toolbar", True)))
        self.autostart = QCheckBox("开机自动启动")
        self.autostart.setChecked(bool(self.config.get("autostart", False)))
        self.proxy = QLineEdit(self.config.get("proxy") or "")
        self.proxy.setPlaceholderText("如 http://127.0.0.1:7890（国际接口需要；留空不走代理）")
        self.debug_log = QCheckBox("写调试日志到 promptpop.log")
        self.debug_log.setChecked(bool(self.config.get("debug_log")))
        self.notify_done = QCheckBox("生成完成后弹托盘通知")
        self.notify_done.setChecked(bool(self.config.get("notify_on_done", True)))
        self.retention = QLineEdit(str(self.config.get("history_retention_days", 0) or 0))
        self.max_input = QLineEdit(str(self.config.get("max_input_chars", 20000) or 0))
        self.max_input.setPlaceholderText("0 = 不限制；超限会在提交时拦截")
        self.hotkey = QLineEdit(self.config.get("hotkey") or "<ctrl>+<shift>+<space>")
        self.hotkey.setPlaceholderText("如 Ctrl+Shift+Space / Ctrl+Alt+K")

        form.addRow("默认提供商", self.provider)
        form.addRow("模型", self.model)
        form.addRow("DeepSeek API Key", _key_row(self.key_deepseek, "deepseek"))
        form.addRow("OpenAI API Key", _key_row(self.key_openai, "openai"))
        form.addRow("Ollama 地址", self.ollama_url)
        form.addRow("主题", self.theme)
        form.addRow("温度 (0~2)", self.temperature)
        form.addRow("", self.sel_toolbar)
        form.addRow("", self.autostart)
        form.addRow("LLM 代理", self.proxy)
        form.addRow("", self.debug_log)
        form.addRow("", self.notify_done)
        form.addRow("历史保留天数(0=不限)", self.retention)
        form.addRow("单条输入上限(字)", self.max_input)
        form.addRow("热键唤起", self.hotkey)
        self.hotkey_hint = QLabel("")
        self.hotkey_hint.setWordWrap(True)
        self.hotkey_hint.setStyleSheet("color:#c9a227; font-size:11px;")
        self.hotkey.textChanged.connect(self._update_hotkey_hint)
        form.addRow("", self.hotkey_hint)
        self._update_hotkey_hint(self.hotkey.text())  # 初始提示（默认含 Space）

        # 连通性预检（异步，不阻塞界面）
        ping_row = QHBoxLayout()
        self.b_ping = QPushButton("测试连接")
        self.ping_label = QLabel("")
        self.ping_label.setWordWrap(True)
        self.b_ping.clicked.connect(self._on_ping)
        ping_row.addWidget(self.b_ping)
        ping_row.addWidget(self.ping_label, 1)
        form.addRow("连通性", ping_row)
        # 基本 tab 表单 15+ 行，小屏（768p/高 DPI）会撑爆对话框——套滚动区
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidget(w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        return scroll

    # ---------- 自定义端点：任意 OpenAI 兼容服务（OpenRouter/vLLM/自建网关） ----------
    def _endpoints_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("添加任意 OpenAI 兼容端点（如 OpenRouter、本地 vLLM、自建网关）。"
                          "这些端点不在内置列表里时，可在此接入。"))

        self.custom_list = QListWidget()
        self.custom_list.setSelectionMode(QListWidget.SingleSelection)
        from .providers import _iter_custom
        for c in _iter_custom(self.config.data):
            self._add_custom_row(c)
        v.addWidget(self.custom_list, 1)

        row = QHBoxLayout()
        b_add = QPushButton("+ 添加端点")
        b_add.clicked.connect(self._on_add_endpoint)
        b_edit = QPushButton("编辑选中")
        b_edit.setToolTip("修改名称/地址/默认模型（Key 留空 = 不修改已有 Key）")
        b_edit.clicked.connect(self._on_edit_endpoint)
        b_del = QPushButton("- 删除选中")
        b_del.clicked.connect(self._on_del_endpoint)
        row.addWidget(b_add)
        row.addWidget(b_edit)
        row.addWidget(b_del)
        row.addStretch(1)
        v.addLayout(row)

        note = QLabel("提示：Key 明文存于本地配置文件（自定义端点多为自建/网关，无钥匙串支持）。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888; font-size:11px;")
        v.addWidget(note)
        return w

    def _add_custom_row(self, c):
        name = c.get("label") or c.get("name") or c.get("id") or "（未命名）"
        url = c.get("base_url", "")
        has_key = "•" if c.get("api_key") else ""
        item = QListWidgetItem("%s  ·  %s  %s" % (name, url, has_key))
        item.setData(Qt.UserRole, c.get("id") or c.get("name") or "")
        self.custom_list.addItem(item)

    def _on_add_endpoint(self):
        dlg = _CustomProviderDialog(self, ui_util)
        if ui_util.exec_dialog(dlg):
            entry = dlg.to_entry()
            add_custom_provider(self.config.data, entry["label"], entry["base_url"],
                               entry["default_model"], entry.get("api_key", ""),
                               entry.get("needs_key", True))
            self._refresh_custom_list()

    def _on_edit_endpoint(self):
        """编辑选中端点：预填当前值，同名（id）保存即更新——此前只能删了重加。"""
        item = self.custom_list.currentItem()
        if item is None:
            return
        pid = item.data(Qt.UserRole)
        cur = None
        for c in (self.config.data.get("custom_providers") or []):
            if (c.get("id") or c.get("name")) == pid:
                cur = c
                break
        if cur is None:
            return
        dlg = _CustomProviderDialog(self, ui_util, initial=cur)
        if ui_util.exec_dialog(dlg):
            entry = dlg.to_entry()
            if entry["label"] != pid:
                remove_custom_provider(self.config.data, pid)   # 改名 = 换 id
            add_custom_provider(self.config.data, entry["label"], entry["base_url"],
                               entry["default_model"],
                               entry.get("api_key", "") or cur.get("api_key", ""),
                               entry.get("needs_key", True))
            self._refresh_custom_list()

    def _refresh_custom_list(self):
        from .providers import _iter_custom
        self.custom_list.clear()
        for c in _iter_custom(self.config.data):
            self._add_custom_row(c)

    def _on_del_endpoint(self):
        item = self.custom_list.currentItem()
        if item is None:
            return
        pid = item.data(Qt.UserRole)
        remove_custom_provider(self.config.data, pid)
        self.custom_list.takeItem(self.custom_list.row(item))

    def _on_ping(self):
        # 连点会覆盖线程引用 → 旧对象被 GC 时线程仍在跑 → 崩溃
        prev = getattr(self, "_ping_thread", None)
        if prev is not None and prev.isRunning():
            return
        pid = self.provider.currentData()
        base_url = resolve(pid, self.config.data)[0]
        proxy = (self.proxy.text().strip() if hasattr(self, "proxy") else "")
        self.ping_label.setText("正在测试…")
        self.b_ping.setEnabled(False)
        th = PingThread(base_url, proxy=proxy, timeout=5.0)
        th.result.connect(self._on_ping_result)
        # 模块级注册表持有引用：本对话框是 exec() 返回即析构的局部对象，
        # 若 ping 还在飞，仅靠 self._ping_thread 会在对话框销毁后立刻被 GC → abort。
        threads.keep_until_finished(th)
        self._ping_thread = th
        th.start()

    def _on_ping_result(self, ok, detail):
        self.b_ping.setEnabled(True)
        # 不断引用、不在此 deleteLater：线程 finished 时会自动 deleteLater。
        # 提前 deleteLater 后再解引用会 double-free；此处只更新 UI。
        if ok:
            self.ping_label.setText("<font color='#2e9e5b'>✓ 可达</font> · %s" % detail)
        else:
            self.ping_label.setText(
                "<font color='#c0433a'>✗ 不可达</font> · 检查网络/代理/地址：%s" % detail)

    def closeEvent(self, event):
        """关闭时断开还在跑的连通性预检线程。

        否则线程完成后会回调到已销毁的对话框，触发
        RuntimeError: Internal C++ object already deleted。
        注意：只断开连接，**不能把 _ping_thread 置 None**——
        那会释放最后一个引用，若线程仍在跑就会被 GC 析构 → 进程 abort。
        引用保留到对象销毁（QThread 运行中禁止析构）。
        """
        th = getattr(self, "_ping_thread", None)
        if th is not None:
            try:
                th.result.disconnect(self._on_ping_result)
            except Exception:
                pass
        super().closeEvent(event)

    def _meta_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("自定义「优化用户指令」meta-prompt（留空用默认）："))
        self.meta_user = QPlainTextEdit(self.config.get("custom_meta_user") or "")
        lay.addWidget(self.meta_user)
        row_u = QHBoxLayout()
        b_load_user = QPushButton("载入默认模板（在此之上改）")
        b_load_user.setToolTip("把内置默认 meta-prompt 填入上方编辑框，便于微调而非从零写")
        b_load_user.clicked.connect(lambda: self._load_default_meta(self.meta_user, "user"))
        row_u.addWidget(b_load_user)
        row_u.addStretch(1)
        lay.addLayout(row_u)
        lay.addWidget(QLabel("自定义「优化系统提示词」meta-prompt（留空用默认）："))
        self.meta_system = QPlainTextEdit(self.config.get("custom_meta_system") or "")
        lay.addWidget(self.meta_system)
        row_s = QHBoxLayout()
        b_load_sys = QPushButton("载入默认模板（在此之上改）")
        b_load_sys.clicked.connect(lambda: self._load_default_meta(self.meta_system, "system"))
        row_s.addWidget(b_load_sys)
        row_s.addStretch(1)
        lay.addLayout(row_s)
        return w

    def _load_default_meta(self, edit, mode):
        """把内置默认模板填入编辑框（覆盖前确认，防误点冲掉已写的自定义内容）。"""
        from .meta_prompt import get_meta_template
        if edit.toPlainText().strip() and not ui_util.exec_confirm(
                self, "载入默认模板",
                "编辑框已有内容，载入将覆盖。\n确定继续？"):
            return
        edit.setPlainText(get_meta_template(mode))

    # ---------- 备份与迁移：导出/导入配置（config.py 已实现，此前无 UI 入口 ----------
    def _backup_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("导出当前配置到文件（便于备份或迁移到其它电脑）；"
                          "导入会用所选文件覆盖当前配置。"))
        row = QHBoxLayout()
        b_export = QPushButton("导出配置…")
        b_import = QPushButton("导入配置…")
        b_export.clicked.connect(self._on_export_config)
        b_import.clicked.connect(self._on_import_config)
        row.addWidget(b_export)
        row.addWidget(b_import)
        b_opendir = QPushButton("打开配置目录…")
        b_opendir.setToolTip("config.json / 备份 / promptpop.log 都在这里（排障常需）")
        b_opendir.clicked.connect(self._on_open_config_dir)
        row.addWidget(b_opendir)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _on_open_config_dir(self):
        import os
        from .config import config_dir
        d = str(config_dir())
        try:
            if os.name == "nt":
                os.startfile(d)  # noqa: S606 —— 资源管理器打开配置目录
            else:
                import subprocess
                subprocess.Popen(["xdg-open", d])
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "打开失败", "%s\n\n目录：%s" % (e, d))

    def _on_export_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "promptpop-config.json", "JSON (*.json)")
        if not path:
            return
        try:
            self.config.export_to(path)
            ui_util.exec_message(self, "已导出", "配置已导出到：\n%s" % path)
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "导出失败", str(e))

    def _on_import_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "JSON (*.json)")
        if not path:
            return
        if not ui_util.exec_confirm(
                self, "导入配置",
                "导入将覆盖当前配置（自定义端点、Key 等）。\n确定继续？"):
            return
        try:
            self.config.import_from(path)
            ui_util.exec_message(
                self, "已导入",
                "配置已导入。\n为保证全部生效（如已保存的 Key、端点），请重启 PromptPop。")
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "导入失败", str(e))

    def reject(self):
        """取消：还原打开时的配置快照，防止端点增删等改动被静默落盘。"""
        try:
            self.config.data.clear()
            self.config.data.update(self._cfg_snapshot)
        except Exception:
            pass
        super().reject()

    def _update_hotkey_hint(self, text):
        """输入框旁的实时热键风险提示（非阻塞，区别于保存时的拦截）。"""
        from . import util
        combo = util.validate_hotkey(text.strip())
        if not combo:
            self.hotkey_hint.setText("格式示例：Ctrl+Alt+K / Ctrl+Shift+Space")
            self.hotkey_hint.setStyleSheet("color:#888; font-size:11px;")
            return
        block, warning = util.check_hotkey_risk(combo)
        if block:
            self.hotkey_hint.setText("⚠ " + warning)
            self.hotkey_hint.setStyleSheet("color:#e06c5a; font-size:11px;")
        elif warning:
            self.hotkey_hint.setText("⚠ " + warning)
            self.hotkey_hint.setStyleSheet("color:#c9a227; font-size:11px;")
        else:
            self.hotkey_hint.setText("可用")
            self.hotkey_hint.setStyleSheet("color:#5b9e5b; font-size:11px;")

    def _reset_defaults(self):
        """把设置项恢复为默认值（只改控件，不落盘：需再点「保存」才生效，可「取消」放弃）。

        保留自定义端点与系统钥匙串里的 API Key（用户数据，重新填代价高）。
        """
        from . import util
        from .config import DEFAULT_CONFIG as D
        if not ui_util.exec_confirm(
                self, "恢复默认设置",
                "将把设置项恢复为默认值。\n"
                "自定义端点与已保存的 API Key 不受影响。\n"
                "恢复后需点击「保存」才会生效。"):
            return
        idx = self.provider.findData(D["provider"])
        if idx >= 0:
            self.provider.setCurrentIndex(idx)
        self.model.setText(D["model"])
        self.ollama_url.setText(D["ollama_base_url"])
        self.theme.setCurrentText(D["theme"])
        self.temperature.setText(str(D["temperature"]))
        self.sel_toolbar.setChecked(D["selection_toolbar"])
        self.autostart.setChecked(D["autostart"])
        self.proxy.setText(D["proxy"])
        self.debug_log.setChecked(D["debug_log"])
        self.notify_done.setChecked(D["notify_on_done"])
        self.retention.setText(str(D["history_retention_days"]))
        self.max_input.setText(str(D["max_input_chars"]))
        self.hotkey.setText(util.format_hotkey(D["hotkey"]))
        self.meta_user.setPlainText(D["custom_meta_user"])
        self.meta_system.setPlainText(D["custom_meta_system"])
        ui_util.exec_message(self, "已恢复默认", "设置已恢复为默认值，点击「保存」后生效。")

    def _save(self):
        from . import util
        t = util.validate_temperature(self.temperature.text().strip())
        if t is None:
            ui_util.exec_warning(self, "参数无效", "温度须为 0~2 之间的数字。")
            return
        # 留空 = 用内置默认地址（绝大多数用户不会改），不能因此拦住保存
        ollama_url = self.ollama_url.text().strip()
        if ollama_url and not util.validate_base_url(ollama_url):
            ui_util.exec_warning(self, "参数无效", "Ollama 地址须以 http:// 或 https:// 开头。")
            return
        # 校验必须全部前置：否则热键校验失败时，Key 已经写进钥匙串了（等于半保存）
        hk = util.validate_hotkey(self.hotkey.text().strip())
        if hk is None:
            ui_util.exec_warning(self, "参数无效",
                                "热键格式无效，示例：Ctrl+Shift+Space 或 Ctrl+Alt+K")
            return
        block, warning = util.check_hotkey_risk(hk)
        if block:
            ui_util.exec_warning(self, "热键不可用", warning)
            return
        # 非阻断的易冲突提示改为输入框旁的实时标签（_update_hotkey_hint），
        # 不在保存时弹模态框（否则默认 Ctrl+Shift+Space 每次保存都弹窗）
        self.config.set("provider", self.provider.currentData())
        self.config.set("model", self.model.text().strip())
        kd = self.key_deepseek.text().strip()
        key_fail = []
        if kd and not secrets.set_key("deepseek", kd):
            key_fail.append("DeepSeek")
        ko = self.key_openai.text().strip()
        if ko and not secrets.set_key("openai", ko):
            key_fail.append("OpenAI")
        if key_fail:
            # 钥匙串后端故障时不能装作保存成功，否则用户下次优化才发现「未配置 Key」
            ui_util.exec_warning(
                self, "Key 保存失败",
                "无法写入系统钥匙串：%s。\n可能原因：未安装 keyring、凭据管理器不可用或组策略禁用。\n"
                "本次不会保存该 Key，请先解决钥匙串问题后重试。"
                % "、".join(key_fail))
            return
        # 热键「试注册」必须放在**任何落盘之前**：失败则本次保存整体放弃，磁盘与内存都不动。
        # （原先放在 config.save() 之后：失败时已写盘、再回滚 hotkey 又写一次，
        #   若用户随后点「取消」，reject() 只回滚内存不回滚磁盘 → 内存/磁盘不一致。）
        old_hk = self.config.get("hotkey")
        if hk != old_hk and self.hotkey_restart is not None:
            ok, err = self.hotkey_restart(hk)
            if not ok:
                # 输入框退回「实际生效」的组合，避免界面显示新值、实际没生效
                self.hotkey.setText(util.format_hotkey(old_hk) if old_hk else "")
                ui_util.exec_warning(
                    self, "热键不可用",
                    "%s\n\n已保留原热键 %s，请换一个组合后重试。"
                    % (err or "无法注册该热键", util.format_hotkey(old_hk or "")))
                return
        self.config.set("ollama_base_url", ollama_url)
        self.config.set("theme", self.theme.currentText())
        try:
            self.config.set("temperature", float(self.temperature.text().strip() or 0.3))
        except ValueError:
            self.config.set("temperature", 0.3)
        self.config.set("selection_toolbar", self.sel_toolbar.isChecked())
        want_autostart = self.autostart.isChecked()
        self.config.set("autostart", want_autostart)
        self.config.set("proxy", self.proxy.text().strip())
        self.config.set("debug_log", self.debug_log.isChecked())
        self.config.set("notify_on_done", self.notify_done.isChecked())
        try:
            self.config.set("history_retention_days",
                            max(0, int(self.retention.text().strip() or 0)))
        except ValueError:
            self.config.set("history_retention_days", 0)
        try:
            self.config.set("max_input_chars", max(0, int(self.max_input.text().strip() or 0)))
        except ValueError:
            self.config.set("max_input_chars", 20000)
        self.config.set("hotkey", hk)
        self.config.set("custom_meta_user", self.meta_user.toPlainText())
        self.config.set("custom_meta_system", self.meta_system.toPlainText())
        self.config.save()
        from . import debuglog
        debuglog.configure(self.debug_log.isChecked())
        if want_autostart:
            autostart.enable()
        else:
            autostart.disable()
        if hk and hk != old_hk and self.hotkey_restart is None:
            self.hotkey_changed.emit(hk)   # 无回调时退回信号（兼容旧路径/测试）
        self.accept()


class _CustomProviderDialog(QDialog):
    """添加/编辑自定义 OpenAI 兼容端点的小对话框。"""

    def __init__(self, parent=None, ui_util_mod=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("添加自定义端点" if not initial else "编辑自定义端点")
        self.setMinimumWidth(460)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("如 OpenRouter / 本地 vLLM（用于下拉显示）")
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://openrouter.ai/api/v1")
        self.model = QLineEdit()
        self.model.setPlaceholderText("默认模型名，如 qwen/qwen-2.5-7b")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.needs_key = QCheckBox("需要 API Key")
        self.needs_key.setChecked(True)
        form.addRow("名称", self.name)
        form.addRow("Base URL", self.base_url)
        form.addRow("默认模型", self.model)
        form.addRow("API Key", self.key)
        form.addRow("", self.needs_key)
        if initial:
            self.name.setText(initial.get("label") or initial.get("id") or "")
            self.base_url.setText(initial.get("base_url", ""))
            self.model.setText(initial.get("default_model", ""))
            self.needs_key.setChecked(bool(initial.get("needs_key", True)))
            if initial.get("api_key"):
                self.key.setPlaceholderText("已保存（留空 = 不修改）")
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _validate(self):
        import promptpop.util as util
        name = self.name.text().strip()
        url = self.base_url.text().strip()
        if not name:
            QMessageBox.warning(self, "缺少名称", "请填写端点名称。")
            return
        if not util.validate_base_url(url):
            QMessageBox.warning(self, "地址无效", "Base URL 须以 http:// 或 https:// 开头。")
            return
        self.accept()

    def to_entry(self):
        return {
            "label": self.name.text().strip(),
            "base_url": self.base_url.text().strip(),
            "default_model": self.model.text().strip(),
            "api_key": self.key.text().strip(),
            "needs_key": self.needs_key.isChecked(),
        }
