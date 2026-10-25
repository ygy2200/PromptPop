"""弹窗显示辅助：确保对话框/消息框可靠地压在「置顶浮窗」之上。

背景：OverlayWindow 用 Qt.WindowStaysOnTopHint | Qt.Tool 常驻最前。
Windows 下，以它为父窗口、但自身没有 StaysOnTopHint 的对话框会被压在下面
（表现：点「库」「设置」后窗口像没反应，其实被主页面挡住了）。

统一做法：任何由浮窗打开的模态弹窗，都先补上置顶标志再 exec。
"""
from PySide6.QtCore import Qt


# ---------- 全局主题（v0.7.9 R23） ----------
# 此前 QSS 只设置在浮窗上——设置/库对话框/消息框永远系统默认色、
# 工具条永远暗色，亮主题用户看到三套观感。提升为 Application 级后全局统一；
# #panel/#title/#status 等对象名选择器只命中浮窗，通用选择器惠及其余对话框。
DARK_QSS = """
#panel { background: #1e1f24; border: 1px solid #3a3d47; border-radius: 12px; }
QLabel { color: #e6e6e6; }
#title { color: #ffd76a; font-weight: bold; font-size: 14px; }
QPlainTextEdit { background: #26272e; color: #e6e6e6; border: 1px solid #3a3d47;
                border-radius: 8px; padding: 6px; selection-background-color: #4a5b8a; }
QLineEdit { background: #26272e; color: #e6e6e6; border: 1px solid #3a3d47; border-radius: 6px; padding: 3px 6px; }
QPushButton { background: #33353d; color: #e6e6e6; border: 1px solid #454852; border-radius: 7px; padding: 5px 12px; }
QPushButton:hover { background: #3d4048; }
QPushButton#primary { background: #c0433a; border: 1px solid #d05a50; font-weight: bold; }
QPushButton#primary:hover { background: #d04a40; }
QPushButton:disabled { color: #7a7d85; background: #2a2b31; }
QComboBox { background: #33353d; color: #e6e6e6; border: 1px solid #454852; border-radius: 6px; padding: 3px 8px; }
#status { color: #9aa0aa; font-size: 12px; }
"""

LIGHT_QSS = """
#panel { background: #f5f6f8; border: 1px solid #d0d3da; border-radius: 12px; }
QLabel { color: #23262b; }
#title { color: #b8860b; font-weight: bold; font-size: 14px; }
QPlainTextEdit { background: #ffffff; color: #23262b; border: 1px solid #d0d3da;
                border-radius: 8px; padding: 6px; selection-background-color: #bcd0f0; }
QLineEdit { background: #ffffff; color: #23262b; border: 1px solid #d0d3da; border-radius: 6px; padding: 3px 6px; }
QPushButton { background: #eceef2; color: #23262b; border: 1px solid #c9ccd4; border-radius: 7px; padding: 5px 12px; }
QPushButton:hover { background: #e0e3e9; }
QPushButton#primary { background: #c0433a; border: 1px solid #d05a50; color: #ffffff; font-weight: bold; }
QPushButton#primary:hover { background: #d04a40; }
QPushButton:disabled { color: #a0a4ab; background: #f0f1f4; }
QComboBox { background: #ffffff; color: #23262b; border: 1px solid #c9ccd4; border-radius: 6px; padding: 3px 8px; }
#status { color: #6b7280; font-size: 12px; }
"""


def apply_app_theme(theme):
    """Application 级主题应用（浮窗/对话框/工具条统一观感）。"""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(DARK_QSS if theme == "dark" else LIGHT_QSS)


def make_topmost(widget):
    """给窗口补上 WindowStaysOnTopHint（已有时不做改动）。返回同一对象。"""
    flags = widget.windowFlags()
    if not (flags & Qt.WindowStaysOnTopHint):
        widget.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
    return widget


def exec_dialog(dlg):
    """显示模态对话框并置顶（替代裸 dlg.exec()）。返回 exec() 的结果。"""
    make_topmost(dlg)
    dlg.show()          # 先 show 拿到原生句柄，再提升 z-order
    dlg.raise_()
    dlg.activateWindow()
    return dlg.exec()


def exec_message(parent, title, text, icon=None, buttons=None):
    """置顶的消息框（替代 QMessageBox.information/warning 静态方法）。"""
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    if icon is not None:
        box.setIcon(icon)
    if buttons is not None:
        box.setStandardButtons(buttons)
    return exec_dialog(box)


def exec_warning(parent, title, text):
    """置顶的警告框（替代 QMessageBox.warning 静态方法）。"""
    from PySide6.QtWidgets import QMessageBox
    return exec_message(parent, title, text, icon=QMessageBox.Warning)


def exec_confirm(parent, title, text, default_yes=False):
    """置顶的 Yes/No 确认框。返回 True 表示用户选 Yes。

    用于删除等不可逆操作前的确认——替代裸 QMessageBox.question（会被置顶浮窗挡住）。
    """
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No if not default_yes else QMessageBox.Yes)
    return exec_dialog(box) == QMessageBox.Yes


def get_text(parent, title, label, default=""):
    """置顶的文本输入对话框（替代 QInputDialog.getText 静态方法）。

    返回 (text, ok)。
    """
    from PySide6.QtWidgets import QInputDialog
    d = QInputDialog(parent)
    d.setWindowTitle(title)
    d.setLabelText(label)
    d.setTextValue(default)
    d.setOkButtonText("确定")
    d.setCancelButtonText("取消")
    ok = exec_dialog(d)
    return (d.textValue(), bool(ok))


class ScrollableResultDialog:
    """可滚动、可复制的结果展示框（用于 A/B 评估等长文本）。

    QMessageBox 对长文本会截断且无法选中复制，这里用只读文本框替代。
    """

    def __init__(self, parent, title, text):
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
        )
        self.text = text or ""
        dlg = QDialog(parent)
        dlg.setWindowTitle(title)
        dlg.resize(640, 460)
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText(self.text)
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        b_copy = QPushButton("复制")
        b_close = QPushButton("关闭")
        row.addStretch(1)
        row.addWidget(b_copy)
        row.addWidget(b_close)
        lay.addLayout(row)

        def _copy():
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(box.toPlainText())
            b_copy.setText("已复制 ✓")

        b_copy.clicked.connect(_copy)
        b_close.clicked.connect(dlg.accept)
        self._dlg = dlg

    def exec(self):
        return exec_dialog(self._dlg)
