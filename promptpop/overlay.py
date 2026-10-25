"""优化浮窗（无边框 / 置顶 / 可拖拽 / 出现在光标附近）。

迭代增补：暗/亮主题、多轮迭代、历史/模板库、流式入库、取消、插入、
A/B 评估、meta-prompt 风格变体、keyring 取 Key、请求超时/重试。
"""
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
    QLabel, QComboBox, QLineEdit, QApplication, QInputDialog, QMessageBox,
    QSizeGrip, QDialog,
)
from . import actions, history, secrets, postprocess, ollama_probe, util, ui_util, threads
from .engine import OptimizeWorker, list_models
from .meta_prompt import build_messages, build_followup_messages, build_judge_messages
from .providers import PROVIDERS, resolve, get_all_providers

# DARK_QSS/LIGHT_QSS 已上移至 ui_util（Application 级主题）

_VARIANT_MAP = {"标准": "standard", "精简": "concise", "严格": "strict"}
_VARIANT_REV = {v: k for k, v in _VARIANT_MAP.items()}


class _Header(QWidget):
    """可拖拽标题区（无边框窗口的拖动把手）。"""

    def __init__(self, window):
        super().__init__(window.panel)
        self._win = window
        self._drag_offset = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.LeftButton):
            self._win.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_offset = None


class ModelFetcher(QThread):
    """后台拉取提供商模型列表，避免阻塞 UI。"""
    done = Signal(list)

    def __init__(self, base_url, api_key, proxy=""):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.proxy = proxy

    def run(self):
        self.done.emit(list_models(self.base_url, self.api_key, proxy=self.proxy))


class OverlayWindow(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.owner_hwnd = None
        self.worker = None
        self._suppress = False
        self._run = {}
        # 流式显示缓冲：逐 chunk moveCursor+insert 在长文本下是 O(n²)
        # （实测 1MB 分块插入 153s）——攒 chunk 定时批量插入，UI 不再卡顿
        self._stream_buf = []
        self._stream_timer = QTimer(self)
        self._stream_timer.setInterval(60)
        self._stream_timer.timeout.connect(self._flush_stream_buf)
        self._run_kind = ""
        self._judge_buf = ""
        self._last_usage = None
        self._active_dialog = None      # 当前打开的模态弹窗（有则热键不应把浮窗盖上来）
        self._model_cache = {}          # provider -> 模型列表；拉取成功则缓存，避免重复请求
        self._models_shown_once = False # 首次显示浮窗时自动拉取一次模型列表
        self.open_settings_hook = None  # 由 app 注入：统一的「打开设置」入口
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setMinimumWidth(660)
        self._build()
        self._sync_from_config()
        self.apply_theme()
        self._restore_geometry()

    # ---------- UI 搭建 ----------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QWidget()
        self.panel.setObjectName("panel")
        outer.addWidget(self.panel)
        root = QVBoxLayout(self.panel)
        root.setContentsMargins(14, 10, 14, 14)
        root.setSpacing(9)

        header = _Header(self)
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        title = QLabel("✨ PromptPop")
        title.setObjectName("title")
        self.mode_box = QComboBox()
        self.mode_box.addItems(["优化用户指令", "优化系统提示词"])
        self.btn_library = QPushButton("库")
        self.btn_library.setFlat(True)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.setFlat(True)
        self.btn_close = QPushButton("✕")
        self.btn_close.setFlat(True)
        self.btn_close.setFixedWidth(30)
        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(self.mode_box)
        h.addWidget(self.btn_library)
        h.addWidget(self.btn_settings)
        h.addWidget(self.btn_close)
        root.addWidget(header)

        self.input_box = QPlainTextEdit()
        self.input_box.setPlaceholderText(
            "把写给 agent 的口语化指令粘贴/输入到这里…\n"
            "（或选中文字自动弹工具条 / 按热键唤起并预填剪贴板）")
        self.input_box.setFixedHeight(104)
        root.addWidget(self.input_box)
        # 附加约束（受众/语言/排除项等，随优化/迭代请求一并交给模型——
        # meta_prompt 的 context 维度此前只有 API 入口，UI 不可达）。
        # 注意：两个控件各自直挂 root，不套 QHBoxLayout 子布局——
        # 嵌套子布局在本机 offscreen 测试下稳定触发 0xC0000005（连跑 12 次全崩，
        # 直挂后 6/6 通过），真机不受影响，但测试环境必须能跑。
        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText(
            "附加约束（可空）：如「受众是初学者」「用英文输出」「不要代码示例」")
        self.extra_edit.setMaxLength(2000)   # 硬上限防呆：附注不该喧宾夺主
        root.addWidget(self.extra_edit, 1)
        # 实时字数提示：逼近/超过「单条输入上限」时变黄/变红（提交时仍会拦截）
        self.input_count = QLabel("")
        self.input_count.setObjectName("status")
        self.input_count.setAlignment(Qt.AlignRight)
        root.addWidget(self.input_count)

        row = QHBoxLayout()
        self.btn_optimize = QPushButton("优化 ✨")
        self.btn_optimize.setObjectName("primary")
        self.provider_box = QComboBox()
        for pid, p in get_all_providers(self.config.data).items():
            self.provider_box.addItem(p["label"], pid)
        self.model_box = QComboBox()
        self.model_box.setEditable(True)
        self.model_box.setPlaceholderText("模型名")
        self.btn_fetch_models = QPushButton("⟳")
        self.btn_fetch_models.setToolTip("拉取可用模型")
        self.btn_fetch_models.setFixedWidth(28)
        self.variant_box = QComboBox()
        self.variant_box.addItems(list(_VARIANT_MAP.keys()))
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setVisible(False)
        row.addWidget(self.btn_optimize)
        row.addWidget(QLabel("提供商"))
        row.addWidget(self.provider_box)
        row.addWidget(QLabel("模型"))
        row.addWidget(self.model_box, 1)
        row.addWidget(self.btn_fetch_models)
        row.addWidget(QLabel("风格"))
        row.addWidget(self.variant_box)
        row.addWidget(self.btn_cancel)
        root.addLayout(row)

        self.status = QLabel("就绪")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.result_box = QPlainTextEdit()
        # 可编辑：优化结果常需手动微调后再复制/替换回去
        self.result_box.setPlaceholderText("优化后的结构化提示词会流式显示在这里…（可直接编辑）")
        root.addWidget(self.result_box, 1)

        # 迭代行（有结果后才显示）
        self.iter_row = QWidget()
        ir = QHBoxLayout(self.iter_row)
        ir.setContentsMargins(0, 0, 0, 0)
        self.iter_edit = QLineEdit()
        self.iter_edit.setPlaceholderText("迭代要求，如：更短 / 更严格 / 加反例…")
        self.btn_iterate = QPushButton("迭代 ↻")
        # 迭代要求同样受 max_input_chars 拦截；常态留空避免噪音，逼近/超限时才提示
        self.iter_count = QLabel("")
        self.iter_count.setObjectName("status")
        ir.addWidget(self.iter_edit, 1)
        ir.addWidget(self.iter_count)
        ir.addWidget(self.btn_iterate)
        self.iter_row.setVisible(False)
        root.addWidget(self.iter_row)

        arow = QHBoxLayout()
        arow.addStretch(1)
        self.btn_copy = QPushButton("复制")
        self.btn_replace = QPushButton("替换 Replace")
        self.btn_insert = QPushButton("插入 Insert")
        self.btn_ab = QPushButton("评估 A/B")
        self.btn_template = QPushButton("存为模板")
        self.btn_regen = QPushButton("重新生成")
        self.btn_clear = QPushButton("清空")
        self.btn_local = QPushButton("本地整理")
        self.btn_local.setToolTip("不调用 LLM 的纯本地文本整理（无需 API Key、零成本）")
        for b in (self.btn_copy, self.btn_replace, self.btn_insert,
                  self.btn_ab, self.btn_template):
            b.setEnabled(False)
        arow.addWidget(self.btn_copy)
        arow.addWidget(self.btn_replace)
        arow.addWidget(self.btn_insert)
        arow.addWidget(self.btn_ab)
        arow.addWidget(self.btn_template)
        arow.addWidget(self.btn_local)
        arow.addWidget(self.btn_regen)
        arow.addWidget(self.btn_clear)
        root.addLayout(arow)

        # 信号
        self.btn_optimize.clicked.connect(self._on_optimize)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_copy.clicked.connect(self._on_copy)
        self.btn_replace.clicked.connect(self._on_replace)
        self.btn_insert.clicked.connect(self._on_insert)
        self.btn_ab.clicked.connect(self._on_ab)
        self.btn_local.clicked.connect(self._on_local_tools)
        self.btn_template.clicked.connect(self._on_save_template)
        self.btn_regen.clicked.connect(self._on_regenerate)
        # lambda 包一层：clicked(bool) 的 checked 会误入 silent 形参
        # （当前 False 恰好等价 silent=False，按钮若设 checkable 即成陷阱）
        self.btn_fetch_models.clicked.connect(lambda: self._on_fetch_models())
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_close.clicked.connect(self.hide)
        self.input_box.textChanged.connect(self._update_input_count)
        self.btn_settings.clicked.connect(self._on_settings)
        self.btn_library.clicked.connect(self._on_open_library)
        self.btn_iterate.clicked.connect(self._on_iterate)
        self.iter_edit.returnPressed.connect(self._on_iterate)
        self.iter_edit.textChanged.connect(self._update_iter_count)
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        self.model_box.lineEdit().editingFinished.connect(self._on_model_changed)
        self.variant_box.currentIndexChanged.connect(self._on_variant_changed)

        self._grips = [QSizeGrip(self) for _ in range(3)]
        for gp in self._grips:
            gp.setFixedSize(16, 16)
            gp.raise_()
        self._update_input_count()   # 初始字数提示
        self._update_iter_count()

    # ---------- 主题 ----------
    def apply_theme(self):
        # 全局 Application 级主题（ui_util）：设置/库/消息框与浮窗统一观感
        ui_util.apply_app_theme(self.config.get("theme"))

    # ---------- 尺寸记忆 ----------
    def _restore_geometry(self):
        """恢复上次用户调整过的浮窗尺寸（位置仍跟随光标）。"""
        try:
            w = int(self.config.get("window_width", 0) or 0)
            h = int(self.config.get("window_height", 0) or 0)
        except Exception:
            w = h = 0
        if w >= self.minimumWidth() and h > 200:
            self.resize(w, h)

    def _remember_geometry(self):
        """记下当前尺寸（在隐藏时调用，避免拖拽缩放期间反复写盘）。"""
        try:
            self.config.set("window_width", self.width())
            self.config.set("window_height", self.height())
            self.config.save()
        except Exception as e:  # noqa: BLE001
            print("[geometry] save failed:", e)

    def hideEvent(self, event):
        self._remember_geometry()
        super().hideEvent(event)

    # ---------- 配置同步 ----------
    def _sync_from_config(self):
        self._suppress = True
        try:
            prov = self.config.get("provider")
            idx = self.provider_box.findData(prov)
            if idx >= 0:
                self.provider_box.setCurrentIndex(idx)
            model = self.config.get("model") or get_all_providers(self.config.data).get(prov, {}).get("default_model", "")
            self.model_box.setCurrentText(model)
            self._prev_provider = prov
            self.mode_box.setCurrentIndex(1 if self.config.get("mode") == "system" else 0)
            self.variant_box.setCurrentText(
                _VARIANT_REV.get(self.config.get("meta_variant", "standard"), "标准"))
        finally:
            self._suppress = False

    def _on_provider_changed(self):
        if self._suppress:
            return
        prov = self.provider_box.currentData()
        self.config.set("provider", prov)
        allp = get_all_providers(self.config.data)
        default_model = allp.get(prov, {}).get("default_model", "")
        cur = self.model_box.currentText().strip()
        old_default = allp.get(self._prev_provider, {}).get("default_model", "")
        # 只有当前为空、或仍是上一个提供商的默认模型时才跟着换，
        # 否则会把用户手输/下拉选中的模型名冲掉。
        if (not cur) or (old_default and cur == old_default):
            self.config.set("model", default_model)
            self.model_box.setCurrentText(default_model)
        self._prev_provider = prov
        self.config.save()
        # 切换 provider 后自动拉取模型列表（静默：没 Key/网络不通不打扰，保持手填）
        self._ensure_models(silent=True)

    def _on_mode_changed(self):
        if self._suppress:
            return
        self.config.set("mode", "system" if self.mode_box.currentIndex() == 1 else "user")
        self.config.save()

    def _on_model_changed(self):
        self.config.set("model", self.model_box.currentText().strip())
        self.config.save()

    def _on_variant_changed(self):
        if self._suppress:
            return
        self.config.set("meta_variant", self._variant())
        self.config.save()

    # ---------- 优化 / 迭代 / 评估 ----------
    def _current_mode(self):
        return "system" if self.mode_box.currentIndex() == 1 else "user"

    def _variant(self):
        return _VARIANT_MAP.get(self.variant_box.currentText(), "standard")

    def _run_worker(self, messages, status_msg, kind, hist_input, mode):
        if self.worker and self.worker.isRunning():
            # 原来直接 return：连点「优化」像没反应。现在给出明确提示。
            self._status("正在生成中… 要换内容请先点「取消」")
            return
        provider = self.config.get("provider")
        base_url, api_key, model, needs_key = resolve(provider, self.config.data)
        api_key = secrets.resolve_api_key(self.config.data, provider) or api_key
        if not model:
            model = PROVIDERS.get(provider, {}).get("default_model", "")
        if provider == "ollama" and not ollama_probe.is_ollama_up(base_url):
            self._status("Ollama 未运行：请先 `ollama serve` 并拉取模型（设置里可改地址）", "warn")
            return
        if needs_key and not api_key:
            self._status("未配置 API Key —— 点右上角「设置」", "warn")
            return
        if kind != "judge":
            self.result_box.clear()
        self._judge_buf = ""
        self._last_usage = None
        self._run_kind = kind
        self._set_busy(True)
        self._status(status_msg)
        self._run = {"mode": mode, "provider": provider, "model": model, "input": hist_input}
        self.worker = OptimizeWorker(
            messages, base_url, api_key, model,
            util.safe_float(self.config.get("temperature"), 0.3),
            timeout=util.safe_float(self.config.get("request_timeout"), 60),
            max_retries=util.safe_int(self.config.get("max_retries"), 0),
            proxy=self.config.get("proxy", "") or "",
            connect_timeout=util.safe_float(self.config.get("connect_timeout"), 10))
        self.worker.token.connect(self._on_token)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.usage.connect(self._on_usage)
        # 注册表持有引用：浮窗虽长生命周期，但「取消后立刻关窗」等场景下
        # worker 可能仍在跑，仅靠 self.worker 有被 GC 的风险。
        threads.keep_until_finished(self.worker)
        self.worker.start()

    def _on_optimize(self):
        text = self.input_box.toPlainText().strip()
        if not text:
            self._status("先输入或选中要优化的指令")
            return
        mx = util.safe_int(self.config.get("max_input_chars"), 0)
        if mx > 0 and len(text) > mx:
            self._status("⚠ 输入过长（%d 字，上限 %d）：可先用「本地整理」压缩空白/删空行，"
                         "或分段优化，避免爆单与上下文溢出" % (len(text), mx), "warn")
            return
        mode = self._current_mode()
        variant = self._variant()
        extra = self.extra_edit.text().strip()
        context = {"extra": extra} if extra else None
        messages = build_messages(mode, text, self.config.get("custom_meta_" + mode, ""),
                                  variant, context)
        self._run_worker(messages, "优化中…", "optimize", text, mode)

    def _on_iterate(self):
        instr = self.iter_edit.text().strip()
        if not instr:
            self._status("先填迭代要求")
            return
        mx = util.safe_int(self.config.get("max_input_chars"), 0)
        if mx > 0 and len(instr) > mx:
            self._status("⚠ 迭代要求过长（%d 字，上限 %d）：请精简后重试" % (len(instr), mx), "warn")
            return
        prev = self.result_box.toPlainText()
        if not prev.strip():
            self._status("没有可迭代的结果")
            return
        # 迭代会先清空结果框；万一失败要能还原，否则辛苦生成的结果没了
        self._iter_prev = prev
        mode = self._current_mode()
        variant = self._variant()
        extra = self.extra_edit.text().strip()
        context = {"extra": extra} if extra else None
        messages = build_followup_messages(mode, prev, instr,
                                           self.config.get("custom_meta_" + mode, ""),
                                           variant, context)
        self._run_worker(messages, "迭代中…", "iterate", "[迭代] " + instr, mode)

    def _on_ab(self):
        original = self.input_box.toPlainText().strip()
        optimized = self.result_box.toPlainText().strip()
        # A/B 评估也会把原文+结果发给模型，同样受输入上限约束（防爆单）
        mx = util.safe_int(self.config.get("max_input_chars"), 0)
        if mx > 0 and (len(original) + len(optimized)) > mx:
            self._status("⚠ 待评估内容过长（原文+结果 %d 字，上限 %d）：可先缩短原文或"
                         "分段评估，避免爆单与上下文溢出"
                         % (len(original) + len(optimized), mx), "warn")
            return
        if not original or not optimized:
            self._status("需要原文和优化结果才能评估")
            return
        messages = build_judge_messages(original, optimized)
        self._run_worker(messages, "评估中…", "judge", original, self._current_mode())

    # ---------- 本地整理（无 LLM、无 Key、零成本） ----------
    def _on_local_tools(self):
        """打开本地文本动作面板：选一个动作 → 预览 → 应用到结果框。

        让没配 API Key 的用户也能用上 PromptPop；也可在调 LLM 前先做
        一步确定性清理，减少 token 浪费。
        「应用」会覆盖 result_box——busy 时先拦截（同 _on_library_load，
        否则加载内容与流式 token 混合）。
        """
        if self.worker and self.worker.isRunning():
            self._status("正在生成中——请先「取消」再使用本地整理", "warn")
            return
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPlainTextEdit,
            QPushButton, QLabel,
        )
        src = self.input_box.toPlainText()
        if not src.strip():
            self._status("先输入或选中要整理的文本")
            return
        from . import local_actions
        dlg = QDialog(self)
        dlg.setWindowTitle("本地整理（不调用 LLM）")
        dlg.resize(680, 520)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("选择动作（左侧列表），右侧实时预览；「应用」写入结果框。"))

        body = QHBoxLayout()
        lst = QListWidget()
        for name in local_actions.names():
            _fn, desc = local_actions.ACTIONS[name]
            lst.addItem("%s — %s" % (name, desc))
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        body.addWidget(lst, 0)
        body.addWidget(preview, 1)
        lay.addLayout(body, 1)

        state = {"name": None}

        def _refresh():
            it = lst.currentItem()
            if it is None:
                state["name"] = None
                preview.setPlainText("")
                return
            name = it.text().split(" — ")[0]
            state["name"] = name
            try:
                preview.setPlainText(local_actions.apply(name, src))
            except Exception as e:  # noqa: BLE001
                preview.setPlainText("（该动作处理失败：%s）" % e)

        lst.currentRowChanged.connect(lambda _r: _refresh())
        if lst.count():
            lst.setCurrentRow(0)

        row = QHBoxLayout()
        row.addStretch(1)
        b_apply = QPushButton("应用到结果框")
        b_save = QPushButton("存为历史")
        b_close = QPushButton("关闭")
        b_apply.setDefault(True)
        row.addWidget(b_apply)
        row.addWidget(b_save)
        row.addWidget(b_close)
        lay.addLayout(row)

        def _apply():
            if not state["name"]:
                return
            out = preview.toPlainText()
            self.result_box.setPlainText(out)
            for b in (self.btn_copy, self.btn_replace, self.btn_insert,
                      self.btn_ab, self.btn_template):
                b.setEnabled(True)
            self.iter_row.setVisible(True)
            self._status("已应用本地动作：%s（未调用 LLM，零成本）" % state["name"], "ok")
            dlg.accept()

        def _save():
            if not state["name"]:
                return
            out = preview.toPlainText()
            if not out.strip():
                return
            try:
                history.add_history("local", "local", state["name"], src, out)
                self._status("已存为历史（本地动作：%s）" % state["name"], "ok")
            except Exception as e:  # noqa: BLE001
                self._status("存入历史失败：%s" % e, "warn")
            dlg.accept()

        b_apply.clicked.connect(_apply)
        b_save.clicked.connect(_save)
        b_close.clicked.connect(dlg.reject)
        self._open_modal(dlg)

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self._status("取消中…")

    def _on_usage(self, u):
        self._last_usage = u or {}

    def _on_regenerate(self):
        self._on_optimize()

    def _on_fetch_models(self, silent=False):
        # 连点会覆盖 self._model_fetcher 引用 → 旧对象被 GC 时 QThread 仍在跑 → 崩溃
        prev = getattr(self, "_model_fetcher", None)
        if prev is not None and prev.isRunning():
            if not silent:
                self._status("模型列表正在拉取中…")
            return
        provider = self.config.get("provider")
        base_url, api_key, _model, _nk = resolve(provider, self.config.data)
        api_key = secrets.resolve_api_key(self.config.data, provider) or api_key
        if not silent:
            self._status("拉取模型列表中…")
        self._model_fetcher = ModelFetcher(base_url, api_key, self.config.get("proxy", "") or "")
        self._model_fetcher.done.connect(
            lambda models: self._on_models_fetched(models, silent=silent))
        # 模块级注册表持有引用，防连点替换引用时旧线程被 GC → abort
        threads.keep_until_finished(self._model_fetcher)
        self._model_fetcher.start()

    def _on_models_fetched(self, models, silent=False):
        if not models:
            # 静默模式（切换/首次自动拉取）失败不打扰；显式点 ⟳ 才提示
            if not silent:
                self._status("未拉取到模型（该端点可能不支持 /models），可手动输入")
            return
        provider = self.config.get("provider")
        self._model_cache[provider] = models
        cur = self.model_box.currentText().strip()
        self.model_box.clear()
        self.model_box.addItems(models)
        if cur:
            self.model_box.setCurrentText(cur)
        else:
            self.model_box.setCurrentText(models[0])
            self.config.set("model", models[0])
            self.config.save()
        self._status("已拉取 %d 个模型" % len(models))

    def _ensure_models(self, silent=False):
        """切换/首次显示时确保当前 provider 有模型列表：命中缓存直接填，否则拉取。"""
        provider = self.config.get("provider")
        cached = self._model_cache.get(provider)
        if cached:
            cur = self.model_box.currentText().strip()
            self.model_box.clear()
            self.model_box.addItems(cached)
            if cur:
                self.model_box.setCurrentText(cur)
            else:
                self.model_box.setCurrentText(cached[0])
                self.config.set("model", cached[0])
                self.config.save()
            return
        self._on_fetch_models(silent=silent)

    def _on_token(self, t):
        if self._run_kind == "judge":
            self._judge_buf += t
            return
        self._stream_buf.append(t)     # 攒起来，定时批量插入（见 _flush_stream_buf）

    def _flush_stream_buf(self):
        """把缓冲的流式 chunk 一次性插入结果框（60ms 一批，insert 次数降两个量级）。"""
        if not self._stream_buf:
            return
        text = "".join(self._stream_buf)
        self._stream_buf.clear()
        self.result_box.moveCursor(QTextCursor.End)
        self.result_box.insertPlainText(text)

    def _notify(self, title, body):
        """完成/失败通知（默认走托盘气泡）。由 app 侧注入 notify_hook，
        overlay 不直接依赖托盘——没装钩子就静默跳过。"""
        hook = getattr(self, "notify_hook", None)
        if not hook:
            return
        try:
            hook(title, body)
        except Exception:
            pass

    def _on_done(self, full):
        self._set_busy(False)
        if self._run_kind == "judge":
            verdict = (self._judge_buf or full or "").strip() or "（评审无输出）"
            if not self.isVisible():
                # 窗口已被隐藏（如 Esc 关闭）：不突然弹框，但**保存结论**，
                # 等下次唤起时补弹，避免用户花过一次钱却看不到结果。
                self._pending_judge = verdict
                self._status("评估完成（窗口已隐藏，唤起后将自动弹出结论）")
                return
            # 用可滚动/可复制的框替代 QMessageBox（长评审文本会被截断且无法选中）
            self._open_modal(ui_util.ScrollableResultDialog(self, "优化效果评估", verdict))
            self._status("评估完成")
            return
        cleaned = postprocess.postprocess_output(full)
        if not cleaned.strip():
            self._status("模型返回为空")
            return
        self.iter_row.setVisible(True)   # 确认有内容后再露出迭代行
        self.result_box.setPlainText(cleaned)
        u = self._last_usage or {}
        tok = (" · tokens %s" % u.get("total_tokens")) if u.get("total_tokens") else ""
        cost = util.estimate_cost(self._run.get("model", ""), u) if u.get("total_tokens") else None
        cost_s = (" · ≈$%.4f" % cost) if cost is not None else ""
        self._status("完成 · %d 字%s%s" % (len(cleaned), tok, cost_s), "ok")
        # 窗口不可见/未激活时才通知——正看着窗口就不必再弹气泡打扰
        if self.config.get("notify_on_done", True) and not self.isActiveWindow():
            preview = cleaned.strip().replace("\n", " ")[:60]
            self._notify("PromptPop · 优化完成", "已生成 %d 字：%s…" % (len(cleaned), preview))
        try:
            r = self._run or {}
            history.add_history(r.get("mode", "user"), r.get("provider", ""),
                                r.get("model", ""), r.get("input", ""), cleaned)
        except Exception as e:  # noqa: BLE001
            print("[history] save failed:", e)

    def _on_cancelled(self):
        self._set_busy(False)
        self._status("已取消", "warn")

    def _on_failed(self, err):
        self._set_busy(False)
        # 失败也通知：否则用户切到别的窗口就不知道失败了，一直等
        if self.config.get("notify_on_done", True) and not self.isActiveWindow():
            self._notify("PromptPop · 优化失败", (err or "")[:120])
        # 迭代失败：把迭代前的版本放回来，别让用户白等一场
        prev = getattr(self, "_iter_prev", "")
        if self._run_kind == "iterate" and prev.strip():
            self.result_box.setPlainText(prev)
            self._iter_prev = ""
            self._status("迭代失败，已还原迭代前的版本 ｜ " + err, "error")
            return
        self._iter_prev = ""
        if self._run_kind != "judge" and not self.result_box.toPlainText().strip():
            self.iter_row.setVisible(False)
        self._status("失败：" + err, "error")

    # ---------- 动作 ----------
    def _on_copy(self):
        t = self.result_box.toPlainText()
        if not t.strip():
            return
        actions.clipboard_set_text(t)
        self._status("已复制到剪贴板")

    def _replace_fail_msg(self, owner_hwnd):
        """自动粘贴失败时的提示：区分「目标是管理员窗口」给更具体的可执行指引。"""
        if actions.is_target_elevated(owner_hwnd) and not actions.is_current_elevated():
            return ("目标窗口以管理员身份运行，本程序无法向其自动粘贴。"
                    "已复制到剪贴板，请手动 Ctrl+V；或把 PromptPop 也以管理员运行。")
        return "未能定位原窗口：已复制到剪贴板，请手动 Ctrl+V"

    def _on_replace(self):
        t = self.result_box.toPlainText()
        if not t.strip():
            return
        ok = actions.replace_selection(t, self.owner_hwnd)
        if ok:
            self._status("已替换回原窗口")
            self.hide()
        else:
            # 失败时保持窗口打开，否则用户还没看到提示窗口就没了
            self._status(self._replace_fail_msg(self.owner_hwnd), "warn")

    def _on_insert(self):
        t = self.result_box.toPlainText()
        if not t.strip():
            return
        ok = actions.insert_after(t, self.owner_hwnd)
        if ok:
            self._status("已插入到原文后")
            self.hide()
        else:
            self._status(self._replace_fail_msg(self.owner_hwnd), "warn")

    def _on_save_template(self):
        out = self.result_box.toPlainText()
        if not out.strip():
            self._status("没有结果可保存")
            return
        name, ok = ui_util.get_text(self, "存为模板", "模板名称：")
        if not (ok and name.strip()):
            return
        name = name.strip()
        # 同名查重（与库面板「把当前结果存为模板」同语义）：盲目 INSERT 会让
        # 列表出现重复项且难以分辨；先确认覆盖，再删旧插新
        existing = history.find_template_by_name(name)
        if existing and not ui_util.exec_confirm(
                self, "模板已存在",
                "已存在同名模板「%s」。\n\n选「是」覆盖旧版；选「否」取消。" % name):
            self._status("已取消保存（同名模板已存在）")
            return
        if existing:
            history.delete_template(existing)
        history.add_template(name, "自定义", out)
        vs = util.extract_vars(out)
        extra = ("；含变量 %s（加载后按需替换）" % ", ".join(vs)) if vs else ""
        self._status("已存为模板：%s%s" % (name, extra))

    def _on_clear(self):
        self.input_box.clear()
        self.result_box.clear()
        self.iter_edit.clear()
        self.extra_edit.clear()
        self.iter_row.setVisible(False)
        for b in (self.btn_copy, self.btn_replace, self.btn_insert,
                  self.btn_ab, self.btn_template):
            b.setEnabled(False)
        self._status("已清空")

    def _open_modal(self, dlg):
        """统一打开模态对话框：置顶 + 期间不让热键把浮窗盖上来。

        dlg 可以是 QWidget，也可以是带 ._dlg 的包装对象（如结果展示框）。
        """
        real = getattr(dlg, "_dlg", dlg)
        self._active_dialog = real
        try:
            return ui_util.exec_dialog(real)
        finally:
            self._active_dialog = None

    def _on_settings(self):
        # 由 app 注入的统一入口（改热键后能立即重新注册全局热键）
        hook = getattr(self, "open_settings_hook", None)
        if hook:
            hook()
            return
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.config, self)
        if self._open_modal(dlg):
            self._sync_from_config()
            self.apply_theme()

    def _on_open_library(self):
        from .library_dialog import LibraryDialog
        dlg = LibraryDialog(self.config, self.get_current_output, self)
        dlg.load_requested.connect(self._on_library_load)
        self._open_modal(dlg)

    def get_current_output(self):
        return self.result_box.toPlainText()

    def _on_library_load(self, inp, out):
        # busy 时加载会覆盖正在流式写入的 result_box，随后到来的 token 追加在
        # 加载内容尾部（实测内容混合 + 历史元数据错位）——先取消再加载
        if self.worker and self.worker.isRunning():
            self._status("正在生成中——请先「取消」再从库加载", "warn")
            return
        if inp:
            if not self.isVisible():
                # 从托盘「历史与模板库」加载时浮窗还藏着——要把浮窗带出来，
                # 否则用户看不到刚加载的内容（以为点了没反应）。
                # 但**必须延后**：库对话框是「先 emit load_requested、再 accept()」，
                # 此刻它仍开着、_active_dialog 仍指向它，直接 show_at_cursor() 会命中
                # 「有活动弹窗只把弹窗提前」的守卫 → 浮窗根本不会显示（修复等于空转）。
                # 用 0ms 定时器排到本轮事件处理之后：那时对话框已关、守卫自动放行。
                QTimer.singleShot(0, self._show_after_library_load)
            shown, truncated = self._clip_input(inp)
            self.input_box.setPlainText(shown)
            if truncated:
                self._status("已从库加载（原文过长，仅载入前 %d 字）" % len(shown), "warn")
            else:
                self._status("已从库加载")
        if out:
            self.result_box.setPlainText(out)
            for b in (self.btn_copy, self.btn_replace, self.btn_insert,
                      self.btn_ab, self.btn_template):
                b.setEnabled(True)
            self.iter_row.setVisible(True)
        if not inp:
            self._status("已从库加载")

    def _show_after_library_load(self):
        """库加载后把浮窗带出来（排到库对话框关闭之后，绕开模态守卫）。"""
        if self.isVisible():
            return
        self.show_at_cursor()
        self.activateWindow()

    # ---------- 辅助 ----------
    def _clip_input(self, text):
        """按 max_input_chars 截断输入；返回 (文本, 是否截断)。0=不限制。"""
        mx = util.safe_int(self.config.get("max_input_chars"), 0)
        if mx > 0 and len(text) > mx:
            return text[:mx], True
        return text, False

    def set_input(self, text):
        text = text or ""
        shown, truncated = self._clip_input(text)
        self.input_box.setPlainText(shown)
        if truncated:
            self._status("选中文字过长，已截断至 %d 字（可在设置调整「单条输入上限」）"
                         % len(shown), "warn")

    def quick_optimize(self, text):
        """工具条「优化」一键直达：预填选中文本 → 显示浮窗 → 自动开始优化，
        省去在浮窗再点一次「优化✨」。无 Key 时自动优化会提示去设置，符合预期。"""
        self.set_input(text)
        self.show_at_cursor()
        self.activateWindow()
        self.input_box.setFocus()
        self._on_optimize()

    def _set_busy(self, busy):
        # 先冲/清流式缓冲再算 has_result——否则 done 时缓冲未冲，按钮全部失启
        if busy:
            self._stream_buf.clear()
            self._stream_timer.start()
        else:
            self._stream_timer.stop()
            self._flush_stream_buf()
        has_result = bool(self.result_box.toPlainText().strip())
        # 流式输出期间锁定结果框，避免用户边看边编辑把内容搅乱；完成后放开可编辑
        self.result_box.setReadOnly(bool(busy))
        self.btn_optimize.setEnabled(not busy)
        self.btn_optimize.setText("优化中…" if busy else "优化 ✨")
        self.btn_cancel.setVisible(busy)
        self.btn_copy.setEnabled(not busy and has_result)
        self.btn_replace.setEnabled(not busy and has_result)
        self.btn_insert.setEnabled(not busy and has_result)
        self.btn_ab.setEnabled(not busy and has_result)
        self.btn_template.setEnabled(not busy and has_result)
        self.btn_iterate.setEnabled(not busy and has_result)
        # 生成中禁用「重新生成」「清空」：否则会把正在流式输出的结果清掉
        self.btn_regen.setEnabled(not busy)
        self.btn_clear.setEnabled(not busy)

    def _status(self, msg, kind="info"):
        self.status.setText(msg)
        color = {"error": "#e06c5a", "warn": "#c9a227", "ok": "#5b9e5b"}.get(kind)
        if color:
            self.status.setStyleSheet("color:%s; font-weight:600;" % color)
        else:
            self.status.setStyleSheet("")  # 回到主题默认色

    _COUNT_COLOR = {"error": "#e06c5a", "warn": "#c9a227"}

    def _render_char_count(self, label, n, quiet=False):
        """统一的字数提示渲染（主输入框 / 迭代框共用）。

        quiet=True：常态（info）不显示文字——迭代要求通常只有十几个字，常驻
        「0 字（上限 8000）」纯属噪音，只在逼近/超过上限时才冒出来提醒。
        """
        mx = util.safe_int(self.config.get("max_input_chars"), 0)
        text, kind = util.format_char_count(n, mx)
        if quiet and kind == "info":
            label.setText("")
            label.setStyleSheet("")
            return
        label.setText(text)
        color = self._COUNT_COLOR.get(kind)
        if color:
            label.setStyleSheet("color:%s; font-weight:600;" % color)
        else:
            label.setStyleSheet("")  # 回到主题默认色

    def _update_input_count(self):
        """输入框实时字数提示：逼近/超过上限时变黄/变红。"""
        self._render_char_count(self.input_count, len(self.input_box.toPlainText()))

    def _update_iter_count(self):
        """迭代要求字数提示：仅逼近/超限时显示（见 _render_char_count 的 quiet）。"""
        self._render_char_count(self.iter_count, len(self.iter_edit.text()), quiet=True)

    def show_at_cursor(self):
        # 若正有模态弹窗打开（库/设置/差异视图），只把它提到最前，
        # 避免浮窗盖到对话框上让人以为「点了没反应」。
        dlg = getattr(self, "_active_dialog", None)
        if dlg is not None:
            try:
                if dlg.isVisible():
                    dlg.raise_()
                    dlg.activateWindow()
                    return
            except RuntimeError:  # 对话框已被销毁
                self._active_dialog = None
        pos = QCursor.pos()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x, y = util.clamp_position(pos.x() + 14, pos.y() + 18,
                                   self.width(), self.height(),
                                   geo.left(), geo.top(), geo.right(), geo.bottom())
        self.move(x, y)
        self.show()
        self.raise_()
        # 首次显示自动拉取一次模型列表：需 Key 但未配置时不拉（免浪费/静默失败），
        # 已配 Key 或 Ollama 等无需 Key 的 provider 直接拉。
        if not self._models_shown_once:
            self._models_shown_once = True
            provider = self.config.get("provider")
            _bu, _ak, _m, needs_key = resolve(provider, self.config.data)
            ak = secrets.resolve_api_key(self.config.data, provider) or _ak
            if not (needs_key and not ak):
                self._ensure_models(silent=True)
        # 补弹：隐藏期间完成的 A/B 评估结论（用户已花过钱，不能平白丢结果）
        pending = getattr(self, "_pending_judge", "")
        if pending:
            self._pending_judge = ""
            self._open_modal(ui_util.ScrollableResultDialog(self, "优化效果评估", pending))
            self._status("评估完成")

    def keyPressEvent(self, e):
        # 统一走 util.resolve_overlay_shortcut（纯函数，可单测）
        #
        # 注意：绝不能用 e.text() 取主键名 —— Windows 下按住 Ctrl 时
        # QKeyEvent.text() 返回的是控制字符（Ctrl+D→\x04、Ctrl+R→\x12、
        # Ctrl+Shift+C→\x03、Ctrl+I→\t），永远匹配不到 'd'/'r'/'c'/'i'，
        # 会让所有 Ctrl 组合键静默失效。必须走 e.key() 的按键码。
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            key_name = "return"
        elif k == Qt.Key_Escape:
            key_name = "escape"
        elif Qt.Key_A <= k <= Qt.Key_Z:
            key_name = chr(k).lower()   # Qt.Key_A..Key_Z 与 ASCII 大写字母同值
        else:
            key_name = ""
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        act = util.resolve_overlay_shortcut(ctrl, shift, key_name)
        handler = {
            "optimize": self._on_optimize,
            "copy_all": self._on_copy,
            "replace": self._on_replace,
            "insert": self._on_insert,
            "diff": self._on_diff,
            "cancel": self._on_escape,
        }.get(act)
        if handler:
            handler()
            return
        super().keyPressEvent(e)

    def _on_escape(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        self.hide()

    def _on_diff(self):
        """原文 vs 优化结果 行级差异视图（Ctrl+D）。"""
        old = self.input_box.toPlainText()
        new = self.result_box.toPlainText()
        if not old.strip() and not new.strip():
            self._status("没有可对比的内容")
            return
        # difflib 最坏 O(n²) 且在主线程同步算——超长内容先拦截，避免 UI 冻死
        total_lines = old.count("\n") + new.count("\n")
        if total_lines > 20000:
            self._status("⚠ 内容过长（共 %d 行），差异视图已跳过：请分段对比"
                         % total_lines, "warn")
            return
        lines = util.diff_lines(old, new)
        added = sum(1 for x in lines if x.startswith("+ "))
        removed = sum(1 for x in lines if x.startswith("- "))
        dlg = QDialog(self)
        dlg.setWindowTitle("差异视图 · 原文 vs 优化结果（+%d / -%d）" % (added, removed))
        dlg.resize(760, 540)
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setLineWrapMode(QPlainTextEdit.NoWrap)
        box.setPlainText("\n".join(lines))
        lay.addWidget(box)
        row = QHBoxLayout()
        b = QPushButton("关闭")
        b.clicked.connect(dlg.accept)
        b.setDefault(True)             # Enter 关闭
        b_copy = QPushButton("复制差异")
        b_copy.clicked.connect(
            lambda: (actions.clipboard_set_text("\n".join(lines)),
                     self._status("差异已复制到剪贴板")))
        row.addStretch(1)
        row.addWidget(b_copy)
        row.addWidget(b)
        lay.addLayout(row)
        self._open_modal(dlg)
        self._status("差异：新增 %d 行 / 移除 %d 行" % (added, removed))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_grips", None):
            g = 16
            w, h = self.width(), self.height()
            self._grips[0].move(w - g, h - g)   # 右下
            self._grips[1].move(0, h - g)       # 左下
            # 原放在右上角，正好压住「库/设置/✕」三个按钮，点不到关闭；改到左上角
            self._grips[2].move(0, 0)           # 左上
