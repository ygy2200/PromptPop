"""hotkey.py 测试：解析 / 注册 / 冲突检测 / WM_HOTKEY 接收。

脚本式运行（每个测试文件各自起一个 QApplication，避免 pytest 多文件冲突）。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PROMPTPOP_CONFIG_DIR"] = tempfile.mkdtemp(prefix="pp_hk_")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402

sys.path.insert(0, ".")
from promptpop import hotkey  # noqa: E402
from promptpop.hotkey import (parse_combo, MOD_CONTROL, MOD_SHIFT, MOD_ALT,  # noqa: E402
                              MOD_WIN, MOD_NOREPEAT, WM_HOTKEY,
                              WinHotkeyManager, PynputHotkeyManager,
                              create_hotkey_manager, ERROR_HOTKEY_ALREADY_REGISTERED)


def test_parse_combo():
    # 基础组合（validate_hotkey 输出的规范括号形式）
    mods, vk = parse_combo("<ctrl>+<shift>+<space>")
    assert mods == (MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT), mods
    assert vk == 0x20, vk
    # 字母主键（大写 VK）
    mods, vk = parse_combo("<ctrl>+c")
    assert mods == (MOD_CONTROL | MOD_NOREPEAT)
    assert vk == ord("C"), vk
    # Alt + F12
    mods, vk = parse_combo("<alt>+<f12>")
    assert mods == (MOD_ALT | MOD_NOREPEAT)
    assert vk == 0x7B, vk
    # Win 组合
    mods, vk = parse_combo("<cmd>+d")
    assert mods == (MOD_WIN | MOD_NOREPEAT)
    assert vk == ord("D"), vk
    # 非法：缺修饰键
    assert parse_combo("<space>") == (None, None)
    # 非法：无主键
    assert parse_combo("<ctrl>+<shift>") == (None, None)
    # 非法：长度不足
    assert parse_combo("abc") == (None, None)
    # 非法：未知键
    assert parse_combo("<ctrl>+<zzz>") == (None, None)
    # 非法：空
    assert parse_combo("") == (None, None)
    print("[ok] 1. parse_combo 各类组合与非法输入")


def test_roundtrip_validate_to_parse():
    """往返安全：validate_hotkey 能产出的**任何**组合，parse_combo 都必须解析成功。

    这是两侧映射表（util._KEY_MAP/_MOD_MAP 与 hotkey._VK/_WIN_MOD）的一致性契约——
    任何一边加了新键而另一边没跟上，就会表现为「用户填了合法热键，却注册失败」。
    """
    from promptpop import util
    mods = ["ctrl", "control", "shift", "alt", "win", "cmd", "super"]
    keys = (["space", "enter", "return", "esc", "escape", "tab", "up", "down",
             "left", "right", "backspace", "delete", "home", "end",
             "pageup", "pagedown"]
            + ["f%d" % i for i in range(1, 13)]
            + list("abcxyz0189"))
    n = 0
    for m in mods:
        for k in keys:
            combo = util.validate_hotkey("%s+%s" % (m, k))
            assert combo is not None, "validate 拒绝了 %s+%s" % (m, k)
            mods_v, vk = parse_combo(combo)
            assert mods_v is not None and vk is not None, \
                "parse_combo 不认识 validate 产出的 %r（映射表不同步）" % combo
            n += 1
    # 退化输入：两侧必须**一致拒绝**，否则 UI 会显示「可用」而注册失败
    # （只有修饰键 / 没有修饰键 / 单键）
    for bad in ("Ctrl+Shift", "Ctrl", "Alt+Win", "A+B", "F1+F2", "Space"):
        assert util.validate_hotkey(bad) is None, \
            "validate_hotkey 应拒绝退化输入 %r（与 parse_combo 对齐）" % bad
        assert parse_combo(bad) == (None, None), bad
    print("[ok] 2b. 往返安全：%d 个合法组合可解析 + 6 个退化输入两侧一致拒绝" % n)


def test_create_manager_platform():
    # Windows 环境应返回 WinHotkeyManager
    assert isinstance(create_hotkey_manager(), WinHotkeyManager)
    print("[ok] 2. create_hotkey_manager 在 Windows 返回 WinHotkeyManager")


def test_register_conflict_and_errors():
    """冲突（1409）与其它系统错误（mock 掉 user32）的返回文案。"""
    real = hotkey._user32

    class FakeU32:
        def __init__(self, reg_ok, err):
            self._ok = reg_ok
            self._err = err

        def RegisterHotKey(self, *a):
            return self._ok

        def UnregisterHotKey(self, *a):
            return True

        def GetLastError(self):
            return self._err

    try:
        # 被占用 → 明确提示
        hotkey._user32 = lambda: FakeU32(False, ERROR_HOTKEY_ALREADY_REGISTERED)
        m = WinHotkeyManager()
        ok, err = m.register("<ctrl>+<shift>+<space>")
        assert ok is False
        assert "占用" in err, err
        m.unregister()

        # 其它系统错误 → 透出错误码
        hotkey._user32 = lambda: FakeU32(False, 5)
        m2 = WinHotkeyManager()
        ok, err = m2.register("<ctrl>+c")
        assert ok is False
        assert "系统错误 5" in err, err
        m2.unregister()

        # 非法格式 → 直接拒绝（不触碰 Win32）
        m3 = WinHotkeyManager()
        ok, err = m3.register("not-a-combo")
        assert ok is False and "非法" in err, err
    finally:
        # 必须 finally 还原：中途断言失败若把 Fake 留在模块里，会污染后续用例
        hotkey._user32 = real
    print("[ok] 3. 冲突(1409)/其它错误(5)/非法格式 的返回文案")


def test_register_real_and_unregister():
    """真实注册一次（best-effort）：验证 ctypes 签名正确，并立即注销。

    若本机该组合已被占用，则软跳过（环境原因，非代码缺陷）。
    """
    m = WinHotkeyManager()
    try:
        ok, err = m.register("<ctrl>+<alt>+o")
    except Exception as e:   # noqa: BLE001 — ctypes/参数错误应暴露
        m.unregister()
        raise AssertionError("真实注册抛异常（ctypes 签名疑似有误）：%s" % e)
    if ok:
        assert m._registered is True
        m.unregister()
        assert m._registered is False
        print("[ok] 4. 真实 RegisterHotKey 注册+注销成功（ctypes 签名正确）")
    else:
        print("[skip] 4. 真实注册被本机占用，软跳过（%s）" % err)


def test_native_filter_receives_wm_hotkey():
    """nativeEventFilter 仅对 WM_HOTKEY 且 id 匹配时触发 activated。"""
    m = WinHotkeyManager()
    received = []

    def on_act():
        received.append(1)

    m.activated.connect(on_act)

    # WM_HOTKEY，wParam == _id → 应触发
    msg = wintypes.MSG()
    msg.message = WM_HOTKEY
    msg.wParam = m._id
    m._filter.nativeEventFilter("windows_generic_MSG", ctypes.addressof(msg))
    app.processEvents()
    assert received == [1], received

    # 其它消息（如 WM_MOUSEMOVE=0x0200）→ 不触发
    msg2 = wintypes.MSG()
    msg2.message = 0x0200
    msg2.wParam = m._id
    m._filter.nativeEventFilter("windows_generic_MSG", ctypes.addressof(msg2))
    app.processEvents()
    assert received == [1], received

    # id 不匹配 → 不触发
    msg3 = wintypes.MSG()
    msg3.message = WM_HOTKEY
    msg3.wParam = m._id + 99
    m._filter.nativeEventFilter("windows_generic_MSG", ctypes.addressof(msg3))
    app.processEvents()
    assert received == [1], received

    m.unregister()
    print("[ok] 5. nativeEventFilter 仅对命中 WM_HOTKEY 触发 activated")


def main():
    test_parse_combo()
    test_roundtrip_validate_to_parse()
    test_create_manager_platform()
    test_register_conflict_and_errors()
    test_register_real_and_unregister()
    test_native_filter_receives_wm_hotkey()
    print("HOTKEY TESTS OK")


if __name__ == "__main__":
    main()
