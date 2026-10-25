"""历史 / 模板库对话框（M3）。"""
import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QListWidget,
    QPushButton, QInputDialog, QMessageBox, QWidget, QLabel,
    QLineEdit, QFileDialog,
)
from . import history, util, ui_util


class LibraryDialog(QDialog):
    load_requested = Signal(str, str)  # input_text, output_text

    def __init__(self, config, get_current_output=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.get_current_output = get_current_output or (lambda: "")
        self.setWindowTitle("历史 / 模板库")
        self.setMinimumSize(540, 500)
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._history_tab(), "历史")
        tabs.addTab(self._template_tab(), "模板")
        root.addWidget(tabs)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        close.setDefault(True)          # Enter 关闭
        root.addWidget(close)

    # ---- 历史 ----
    def _history_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.hist_search = QLineEdit()
        self.hist_search.setPlaceholderText("搜索历史（模式/提供商/模型/原文/结果）…")
        lay.addWidget(self.hist_search)
        self.hist_list = QListWidget()
        self._hist = []
        self._hist_all = []
        self._refresh_history()
        # 双击直接加载（与「加载选中到浮窗」等价，少一次点击）
        self.hist_list.itemDoubleClicked.connect(lambda _it: self._load_history())
        lay.addWidget(self.hist_list)
        row = QHBoxLayout()
        btn = QPushButton("加载选中到浮窗")
        btn.clicked.connect(self._load_history)
        b_tag = QPushButton("打标签")
        b_tag.clicked.connect(self._tag_history)
        b_pin = QPushButton("固定/取消固定")
        b_pin.setToolTip("固定项不受「历史保留天数」自动清理（📌 标记）")
        b_pin.clicked.connect(self._toggle_pin)
        b_del = QPushButton("删除选中")
        b_del.clicked.connect(self._del_history)
        b_md = QPushButton("导出 Markdown")
        b_md.clicked.connect(self._export_history_md)
        b_export = QPushButton("导出 JSON")
        b_export.clicked.connect(self._export_history)
        b_clear = QPushButton("清空历史")
        b_clear.clicked.connect(self._clear_history)
        row.addWidget(btn)
        row.addWidget(b_tag)
        row.addWidget(b_del)
        row.addWidget(b_md)
        row.addWidget(b_export)
        row.addWidget(b_clear)
        lay.addLayout(row)
        self.hist_search.textChanged.connect(self._filter_history)
        return w

    def _refresh_history(self):
        # 上限 200→1000：个人使用几个月即触顶，更早记录既浏览不到也导不出
        self._hist_all = history.list_history(1000)
        if len(self._hist_all) >= 1000:
            self._status_hint("仅显示最近 1000 条历史")
        self._apply_hist_filter()

    def _apply_hist_filter(self):
        q = self.hist_search.text().strip() if hasattr(self, "hist_search") else ""
        self.hist_list.clear()
        self._hist = []
        self._hist_ids = []
        self._hist_rows = []        # 当前筛选后的完整行（导出跟随筛选）
        for row in util.filter_history(self._hist_all, q):
            # 兼容新旧列数：(id, ts, mode, provider, model, input, output[, tags[, pinned]])
            hid, ts, mode, prov, model, inp, out = row[:7]
            tags = row[7] if len(row) > 7 else ""
            pinned = bool(row[8]) if len(row) > 8 else False
            t = time.strftime("%m-%d %H:%M", time.localtime(ts))
            preview = (inp or "").strip().replace("\n", " ")[:42]
            tag_s = ("  #%s" % tags.strip()) if (tags or "").strip() else ""
            pin_s = " 📌" if pinned else ""
            self.hist_list.addItem("[%s] %s · %s%s%s" % (t, mode, preview, tag_s, pin_s))
            self._hist.append((inp or "", out or ""))
            self._hist_ids.append(hid)
            self._hist_rows.append(row)

    def _filter_history(self, _text):
        self._apply_hist_filter()

    def _export_history(self):
        import json
        path, _ = QFileDialog.getSaveFileName(self, "导出历史", "promptpop_history.json",
                                              "JSON (*.json)")
        if not path:
            return
        rows = getattr(self, "_hist_rows", None) or self._hist_all
        data = [{"ts": r[1], "mode": r[2], "provider": r[3], "model": r[4],
                 "input": r[5], "output": r[6],
                 "tags": (r[7] if len(r) > 7 else "")} for r in rows]
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            ui_util.exec_message(self, "导出", "已导出 %d 条到：\n%s" % (len(data), path))
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "导出失败", str(e))

    def _load_history(self):
        r = self.hist_list.currentRow()
        if 0 <= r < len(self._hist):
            self.load_requested.emit(*self._hist[r])
            self.accept()

    def _tag_history(self):
        r = self.hist_list.currentRow()
        ids = getattr(self, "_hist_ids", [])
        if not (0 <= r < len(ids)):
            ui_util.exec_message(self, "提示", "请先选中一条历史")
            return
        hid = ids[r]
        cur = ""
        for row in self._hist_all:
            if row[0] == hid:
                cur = (row[7] if len(row) > 7 else "") or ""
                break
        text, ok = ui_util.get_text(self, "打标签",
                                        "标签（逗号分隔，留空=清除）：", default=cur)
        if not ok:
            return
        tags = [t.strip() for t in text.split(",") if t.strip()]
        try:
            history.set_tags(hid, tags)
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "打标签失败", str(e))
            return
        self._refresh_history()

    def _toggle_pin(self):
        """固定/取消固定选中历史（pin_history 此前无生产调用方——README 宣称的
        「固定重要项」用户无法触达，pinned 仅在保留天数清理时被动生效）。"""
        r = self.hist_list.currentRow()
        ids = getattr(self, "_hist_ids", [])
        if not (0 <= r < len(ids)):
            ui_util.exec_message(self, "提示", "请先选中一条历史")
            return
        row = self._hist_rows[r]
        cur = bool(row[8]) if len(row) > 8 else False
        try:
            history.pin_history(ids[r], not cur)
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "固定失败", str(e))
            return
        self._refresh_history()
        self._status_hint("已%s%s" % ("固定 📌" if not cur else "取消固定", ""))

    def _del_history(self):
        """删除选中的单条历史（删除前确认，防误触丢失）。"""
        r = self.hist_list.currentRow()
        ids = getattr(self, "_hist_ids", [])
        if not (0 <= r < len(ids)):
            ui_util.exec_message(self, "提示", "请先选中一条历史")
            return
        hid = ids[r]
        preview = (self.hist_list.item(r).text() or "")[:50] if self.hist_list.item(r) else ""
        if not ui_util.exec_confirm(self, "删除历史",
                                   "确定删除这条历史？此操作不可恢复。\n%s" % preview):
            return
        try:
            history.delete_history(hid)
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "删除失败", str(e))
            return
        self._refresh_history()

    def _clear_history(self):
        """清空全部历史（强确认，防误触丢失全部记录）。"""
        n = len(self._hist_all)
        if n == 0:
            ui_util.exec_message(self, "提示", "当前没有历史可清空")
            return
        if not ui_util.exec_confirm(
                self, "清空全部历史",
                "确定清空全部 %d 条历史？此操作不可恢复。" % n):
            return
        try:
            history.clear_history()
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "清空失败", str(e))
            return
        self._refresh_history()

    def _export_history_md(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出历史为 Markdown",
                                              "promptpop_history.md",
                                              "Markdown (*.md)")
        if not path:
            return
        rows = getattr(self, "_hist_rows", None) or self._hist_all
        try:
            md = history.export_markdown(rows)
            with open(path, "w", encoding="utf-8") as f:
                f.write(md)
            ui_util.exec_message(self, "导出",
                                    "已导出 %d 条（当前筛选结果）到：\n%s" % (len(rows), path))
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "导出失败", str(e))

    # ---- 模板 ----
    def _template_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tpl_list = QListWidget()
        self._tpl = []
        self._refresh_templates()
        # 双击直接加载
        self.tpl_list.itemDoubleClicked.connect(lambda _it: self._load_template())
        lay.addWidget(self.tpl_list)
        row = QHBoxLayout()
        b_load = QPushButton("加载选中")
        b_edit = QPushButton("编辑选中")
        b_del = QPushButton("删除选中")
        b_save = QPushButton("把当前结果存为模板")
        b_export = QPushButton("导出模板")
        b_import = QPushButton("导入模板")
        b_load.clicked.connect(self._load_template)
        b_edit.clicked.connect(self._edit_template)
        b_del.clicked.connect(self._del_template)
        b_save.clicked.connect(self._save_template)
        b_export.clicked.connect(self._export_templates)
        b_import.clicked.connect(self._import_templates)
        row.addWidget(b_load)
        row.addWidget(b_edit)
        row.addWidget(b_del)
        row.addWidget(b_save)
        row.addWidget(b_export)
        row.addWidget(b_import)
        lay.addLayout(row)
        return w

    def _export_templates(self):
        import json
        path, _ = QFileDialog.getSaveFileName(self, "导出模板", "promptpop_templates.json",
                                              "JSON (*.json)")
        if not path:
            return
        data = history.export_templates()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            ui_util.exec_message(self, "导出", "已导出 %d 个模板到：\n%s" % (len(data), path))
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "导出失败", str(e))

    def _import_templates(self):
        import json
        path, _ = QFileDialog.getOpenFileName(self, "导入模板", "",
                                              "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            added, skipped = history.import_templates(data, merge=True)
            ui_util.exec_message(self, "导入",
                                    "导入完成：新增 %d 个，跳过（同名）%d 个" % (added, skipped))
            self._refresh_templates()
        except Exception as e:  # noqa: BLE001
            ui_util.exec_warning(self, "导入失败", str(e))

    def _refresh_templates(self):
        self.tpl_list.clear()
        self._tpl = []
        for tid, name, cat, content in history.list_templates():
            self.tpl_list.addItem("%s  [%s]" % (name, cat))
            self._tpl.append((tid, content))

    def _status_hint(self, msg):
        """库对话框没有状态栏，用窗口标题短暂反馈（不打断操作）。"""
        self.setWindowTitle("历史 / 模板库 — %s" % msg)

    def _load_template(self):
        r = self.tpl_list.currentRow()
        if 0 <= r < len(self._tpl):
            content = self._tpl[r][1]
            content = self._fill_vars(content)
            self.load_requested.emit("", content)
            self.accept()

    def _fill_vars(self, content):
        """模板含 {{var}} 时逐个填值（留空保留占位符，取消亦原样加载）。

        render_template 此前无生产调用方——README 宣称的模板变量只能提示
        变量名，加载后 {{var}} 原样留在文本里，用户只能手改。"""
        vs = util.extract_vars(content)
        if not vs:
            return content
        mapping = {}
        for name in vs:
            text, ok = ui_util.get_text(
                self, "填写模板变量", "变量 {{%s}} 的值（留空保留占位符）：" % name)
            if ok and text.strip():
                mapping[name] = text.strip()
        if not mapping:
            return content
        rendered = util.render_template(content, mapping)
        self._status_hint("已填充 %d 个变量" % len(mapping))
        return rendered

    def _edit_template(self):
        """编辑选中模板的内容（名称/分类不动）。模板是长期资产，
        此前写错只能删了重存。"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QPlainTextEdit
        r = self.tpl_list.currentRow()
        if not (0 <= r < len(self._tpl)):
            return
        tid, content = self._tpl[r]
        name = self.tpl_list.item(r).text().split("  [")[0]
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑模板：%s" % name)
        dlg.resize(640, 480)
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit()
        box.setPlainText(content)
        lay.addWidget(box)
        row = QHBoxLayout()
        b_cancel = QPushButton("取消")
        b_save = QPushButton("保存")
        b_save.setDefault(True)
        row.addStretch(1)
        row.addWidget(b_cancel)
        row.addWidget(b_save)
        lay.addLayout(row)
        b_cancel.clicked.connect(dlg.reject)
        b_save.clicked.connect(dlg.accept)
        if ui_util.exec_dialog(dlg):
            new = box.toPlainText()
            if new != content:
                history.update_template(tid, new)
                self._refresh_templates()
                self._status_hint("已更新模板：%s" % name)

    def _del_template(self):
        r = self.tpl_list.currentRow()
        if not (0 <= r < len(self._tpl)):
            return
        tid, content = self._tpl[r]
        name = self.tpl_list.item(r).text().split("  [")[0]
        # 删除不可逆，先确认（避免误触丢模板）
        if not ui_util.exec_confirm(self, "删除模板",
                                    "确定删除模板「%s」？此操作不可恢复。" % name):
            return
        history.delete_template(tid)
        self._refresh_templates()

    def _save_template(self):
        out = self.get_current_output()
        if not out.strip():
            ui_util.exec_message(self, "提示", "当前没有结果可保存")
            return
        name, ok = ui_util.get_text(self, "存为模板", "模板名称：")
        name = name.strip()
        if not (ok and name):
            return
        # 重名会导致列表出现重复项、难以分辨：先问是否覆盖
        existing = history.find_template_by_name(name)
        if existing:
            if not ui_util.exec_confirm(
                    self, "模板已存在",
                    "已存在同名模板「%s」。\n\n选「是」覆盖旧版；选「否」取消。"
                    % name, default_yes=False):
                return
            history.delete_template(existing)
        history.add_template(name, "自定义", out)
        self._refresh_templates()
        self._status_hint("已保存模板：%s" % name)
