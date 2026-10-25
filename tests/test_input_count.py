"""输入框实时字数提示（format_char_count 纯函数 + _render_char_count 渲染）测试（离屏，无 QApplication）。

R9 新增：util.format_char_count —— 逼近/超过「单条输入上限」返回 warn/error 类别，
供浮窗输入框实时标黄/标红（提交时仍拦截）。
R10 扩展：overlay._render_char_count 的 quiet 分支（迭代框常态留空、逼近/超限才提示）。
刻意不创建 QApplication —— 渲染逻辑以 unbound 方式调用 + 假 label，避开离屏 Qt teardown 崩溃。
运行： QT_QPA_PLATFORM=offscreen python tests/test_input_count.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from promptpop import util  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402


def main():
    # 无上限：只显示字数
    assert util.format_char_count(10, 0) == ("10 字", "info")
    # 有上限、远低于：info + 上限标注
    assert util.format_char_count(100, 20000) == ("100 字（上限 20000）", "info")
    # 逼近上限（>90%）：warn
    assert util.format_char_count(18050, 20000)[1] == "warn"
    # 超过上限：error
    assert util.format_char_count(20001, 20000)[1] == "error"
    assert util.format_char_count(20001, 20000)[0].startswith("超限")
    # 恰好等于上限：仍在限制内（不标红）
    assert util.format_char_count(20000, 20000)[1] == "info"

    # ---- R10：_render_char_count 渲染（unbound 调用，不构造 OverlayWindow）----
    class _FakeOverlay:
        _COUNT_COLOR = OverlayWindow._COUNT_COLOR

        def __init__(self, mx):
            self.config = {"max_input_chars": mx}

    class _Label:
        def __init__(self):
            self.text = ""
            self.style = ""

        def setText(self, t):
            self.text = t

        def setStyleSheet(self, s):
            self.style = s

    render = OverlayWindow._render_char_count
    # quiet=False（主输入框）：常态也显示字数
    lbl = _Label()
    render(_FakeOverlay(20000), lbl, 100)
    assert lbl.text == "100 字（上限 20000）", lbl.text
    assert lbl.style == "", "info 不应染色"
    # quiet=False + 超限：标红
    lbl = _Label()
    render(_FakeOverlay(20000), lbl, 20001)
    assert "超限" in lbl.text and "e06c5a" in lbl.style, (lbl.text, lbl.style)

    # quiet=True（迭代框）：常态（info）留空，不制造噪音
    lbl = _Label()
    render(_FakeOverlay(20000), lbl, 12, quiet=True)
    assert lbl.text == "", "迭代要求很短时不应常驻字数提示"
    # quiet=True + 逼近上限：冒出来提示
    lbl = _Label()
    render(_FakeOverlay(20000), lbl, 19000, quiet=True)
    assert lbl.text and "c9a227" in lbl.style, (lbl.text, lbl.style)
    # quiet=True：从超限删回正常后应清空（否则提示会残留）
    lbl = _Label()
    ov = _FakeOverlay(20000)
    render(ov, lbl, 25000, quiet=True)
    assert "超限" in lbl.text
    render(ov, lbl, 5, quiet=True)
    assert lbl.text == "" and lbl.style == "", "删回正常后残留提示会误导"

    print("INPUT COUNT OK")


if __name__ == "__main__":
    main()
