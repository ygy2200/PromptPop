"""划词小工具条：选中文字后浮在选区附近的按钮栏（PopClip 式）。"""
from PySide6.QtCore import Qt, Signal, QPoint, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QApplication

_AUTO_HIDE_MS = 8000   # 无操作后自动收起，避免小工具条一直挡住选区附近的视线

_QSS_DARK = """
QWidget{background:#1e1f24;border:1px solid #3a3d47;border-radius:10px;}
QPushButton{background:#33353d;color:#e6e6e6;border:1px solid #454852;border-radius:6px;padding:4px 10px;}
QPushButton:hover{background:#3d4048;}
QPushButton#opt{background:#c0433a;border:1px solid #d05a50;font-weight:bold;}
QPushButton#opt:hover{background:#d04a40;}
QPushButton#close{background:#33353d;border:1px solid #454852;padding:4px 4px;}
QPushButton#close:hover{background:#c0433a;}
"""

_QSS_LIGHT = """
QWidget{background:#f5f6f8;border:1px solid #d0d3da;border-radius:10px;}
QPushButton{background:#eceef2;color:#23262b;border:1px solid #c9ccd4;border-radius:6px;padding:4px 10px;}
QPushButton:hover{background:#e0e3e9;}
QPushButton#opt{background:#c0433a;border:1px solid #d05a50;color:#ffffff;font-weight:bold;}
QPushButton#opt:hover{background:#d04a40;}
QPushButton#close{background:#eceef2;border:1px solid #c9ccd4;padding:4px 4px;}
QPushButton#close:hover{background:#c0433a;}
"""


class SelectionToolbar(QWidget):
    optimize = Signal()  # 请求打开完整浮窗优化选中文字
    copy = Signal()      # 复制选中文字
    organize = Signal()  # 打开浮窗的「本地整理」（零成本、无需 API Key）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.source_hwnd = None   # 划词来源窗口（点「优化」时作为替换目标，比事后取前台可靠）
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        self.btn_opt = QPushButton("✨ 优化提示词")
        self.btn_opt.setObjectName("opt")
        self.btn_organize = QPushButton("整理")
        self.btn_organize.setToolTip("本地纯文本整理（无需 API Key）")
        self.btn_copy = QPushButton("复制")
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("close")
        self.btn_close.setFixedWidth(26)
        self.btn_close.setToolTip("关闭工具条")
        lay.addWidget(self.btn_opt)
        lay.addWidget(self.btn_organize)
        lay.addWidget(self.btn_copy)
        lay.addWidget(self.btn_close)
        self.btn_opt.clicked.connect(self.optimize)
        self.btn_organize.clicked.connect(self.organize)
        self.btn_copy.clicked.connect(self.copy)
        self.btn_close.clicked.connect(self.hide)
        self.set_theme("dark")
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.setInterval(_AUTO_HIDE_MS)
        self._auto_hide.timeout.connect(self.hide)
        self.setMouseTracking(True)

    def set_theme(self, theme):
        """跟随全局主题（此前工具条永远暗色，与亮主题浮窗/对话框不一致）。"""
        self.setStyleSheet(_QSS_DARK if theme == "dark" else _QSS_LIGHT)

    def hideEvent(self, event):
        self._auto_hide.stop()
        super().hideEvent(event)

    def changeEvent(self, event):
        # 失焦（用户点了别处）即收起，避免一直挡视线
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self.hide()
        super().changeEvent(event)

    def enterEvent(self, event):
        self._auto_hide.stop()          # 鼠标停在工具条上就不收起
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isVisible():
            self._auto_hide.start()     # 移开后重新开始计时
        super().leaveEvent(event)

    def show_for(self, text, x, y):
        self._text = text
        self.adjustSize()
        # 用「选区所在坐标」判定屏幕：原实现拿自身旧位置判定，
        # 副屏（尤其左侧副屏 x 为负）会错拿主屏边界去夹取。
        screen = QApplication.screenAt(QPoint(int(x), int(y))) \
            or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        w, h = self.width(), self.height()
        nx, ny = x, y + 14
        if nx + w > geo.right():
            nx = geo.right() - w - 6
        if ny + h > geo.bottom():
            ny = y - h - 8
        self.move(max(geo.left() + 4, nx), max(geo.top() + 4, ny))
        self.show()
        self.raise_()
        self._auto_hide.start()

    def selected_text(self):
        return self._text
