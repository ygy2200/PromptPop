# PromptPop 体验优化迭代日志 · 第三轮 10 轮循环（v0.7.5）

> 目标：延续第二轮（v0.7.4），继续「找问题→改→验证」；调研 + 自查 + 独立审查三轮驱动。
> 输入：第二轮遗留（取词真实覆盖率、气泡真机显示、Ollama 系统代理直连三项「待真机确认」）+
> 本轮新调研（热键可靠性、剪贴板、流式中断等）。
> 验收：离屏 UI 冒烟 + 纯函数单测 + 真机项标注「待确认」。
> 假设：只改 `PromptPop/` 源码与测试；不引入重量级新依赖；真机项不谎报。

---

## R1 — 全局热键改用 Windows 原生 RegisterHotKey（替换 pynput）

- **本轮复盘结论**：第二轮 10 轮已收尾（v0.7.4，exe 已出）。遗留三项均为「待真机确认」，离屏不可验证；
  遂转入**新的可离线验证方向**。回顾调研 Top 8 中唯一未实施的高价值项 = **热键可靠性**。
  现状：`app.py` 用 `pynput.keyboard.GlobalHotKeys`（`WH_KEYBOARD_LL` 低级钩子，跑在独立 Python 线程）。
  调研证实其结构性缺陷——**Chromium/Electron/WebView2 窗口在前台时钩子回调可能被系统静默跳过**
  （回调超 `LowLevelHooksTimeout` 预算），表现为「热键没反应且无任何报错」；另有 GIL 丢帧、高完整性进程拦截、
  v1.7.7 Function 键回归（#611）等。对 PromptPop 这种「任意窗口划词后唤起」的场景，这是致命且难排查的缺陷。
- **下一步方向及优先级**：R2 热键冲突/失败的用户可见反馈细化（中）；或按新调研推进（中）。
- **本轮执行结果**：
  - 新增 `promptpop/hotkey.py`：
    - `parse_combo(combo)`：pynput 规范格式 → `(fsModifiers, vk)`，**纯函数可单测**；修饰键映射
      `MOD_CONTROL/SHIFT/ALT/WIN`，主键支持字母/数字/F1–F12/特殊键；并入 `MOD_NOREPEAT` 防长按重复触发。
    - `WinHotkeyManager`：`ctypes` 调 `user32.RegisterHotKey`（hwnd=None → 与 Qt 主线程消息队列绑定），
      `QAbstractNativeEventFilter` 截获 `WM_HOTKEY`（`wintypes.MSG.from_address`）→ `QTimer.singleShot(0)` 抛回主线程发信号。
      `register()` 返回 `(ok, err)`：**1409（ERROR_HOTKEY_ALREADY_REGISTERED）→「已被其它程序占用」**，
      其它错误码透出；`unregister()` 幂等。
    - `PynputHotkeyManager`：非 Windows 兜底（沿用旧实现）。
    - `create_hotkey_manager()`：按平台工厂。
  - `app.py`：删除 `HotkeyBridge`/`_start_hotkey`（pynput 直连），改用 `hotkey.create_hotkey_manager()`；
    `restart_hotkey` 改为 `bridge.register(new_combo)` 并记录 `(active, error)`；`aboutToQuit` 挂 `unregister`；
    失败状态栏文案改为带具体原因（「已被其它程序占用，请换一个组合」）。
  - **纠错（调研所得）**：`GetLastError` 属 `kernel32`（不在 `user32` 导出表），首次实现误挂 user32 → 测试实测报
    `AttributeError: function 'GetLastError' not found`，已改为封装对象内走 kernel32。
  - 验证：新增 `tests/test_hotkey.py`（脚本式，5 项）——① `parse_combo` 各类组合与非法输入；
    ② 工厂在 Windows 返回 `WinHotkeyManager`；③ 冲突(1409)/系统错误(5)/非法格式 的返回文案（mock user32）；
    ④ **真实** `RegisterHotKey` 注册+注销成功（证明 ctypes 签名正确）；⑤ `nativeEventFilter` 仅对命中
    `WM_HOTKEY` 且 id 匹配时触发 `activated`（其它消息/错 id 不触发）。**5/5 通过**。
  - 来源：
    - pynput 钩子在 Chromium 焦点下静默失效：https://github.com/wudaming00/wh-keyboard-ll-chromium
    - pynput v1.7.7 Function 键回归：https://github.com/moses-palmer/pynput/issues/611
    - RegisterHotKey（MS 文档）：https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey
    - ERROR_HOTKEY_ALREADY_REGISTERED=1409：https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--1300-1699-
    - QAbstractNativeEventFilter（Qt 文档）：https://doc.qt.io/qt-6/qabstractnativeeventfilter.html
    - 同类实现参考（traytranslate）：https://github.com/Fusseldieb/traytranslate/blob/main/tray_translate_picker.py
- **遗留问题**：
  - **待真机确认**：原生热键在真实 Chrome/VS Code 焦点下唤起是否确实比 pynput 稳（离屏无法验真实性，
    但机制上由 OS 派发，不依赖钩子）；Win 组合与输入法占用需真机各试一次。
  - `MOD_NOREPEAT` 依赖 Windows 7+（已满足）。
  - 同一进程只注册一个热键 id=1（单实例锁已保证单进程，够用）。

---

## R2 — 热键注册失败的可见反馈 + 失败回滚（闭合 R1 缺口）

- **本轮复盘结论**：R1 完成。发现新缺口：设置里改热键后，`check_hotkey_risk` 只做**静态**判断（拦 Win 组合/提示 Space），
  并不知道新组合**是否已被其它程序占用**——用户看到输入框旁写「可用」，保存后实际注册失败只打到控制台，
  于是「以为改了、按了没反应」。
- **下一步方向及优先级**：R3 托盘补库入口（中）。
- **本轮执行结果**：
  - `settings_dialog.SettingsDialog(..., hotkey_restart=None)`：注入 `(combo) -> (ok, err)` 回调；
    `_save()` 中热键变更后**先尝试真实注册**，失败则 `exec_warning` 明确提示 + **回滚配置**到旧组合 + **不关闭对话框**
    （便于立即换一个）。未注入回调时退回原 `hotkey_changed` 信号（兼容旧路径与既有测试）。
  - `app.restart_hotkey` 增加**回滚语义**：新组合注册失败时把旧组合重新注册回去（`register()` 内部会先 unregister，
    否则「新失败 = 旧也没了」），并返回 `(ok, err)`。`hotkey_state` 增 `combo` 字段。
  - **测试卫生修复**：`SettingsDialog._save()` 会调 `autostart.enable/disable()` 写 HKCU Run 项，
    而测试会调 `_save()` → **跑一次回归就把用户真实的开机自启删掉**。已在 `test_ui_smoke` 顶部把
    `settings_dialog.autostart` 整体替换为无操作桩。
  - 验证：`test_ui_smoke` 新增 `[ok] 8b`——失败路径（告警已弹 + 配置回滚 + 对话框未关）与成功路径
    （正常 accept + 新热键入配置）双断言。**通过**。
  - 来源：R1 调研结论（RegisterHotKey 失败可拿错误码）；QT `QDialog.result()` 语义。
- **遗留问题**：`restart_hotkey` 的回滚依赖 `hotkey_state["combo"]` 记录，仅覆盖本进程内变更；跨重启由配置保证。

---

## R3 — 托盘补「历史与模板库」入口（+ 发现并修复托盘菜单被 GC 的真实缺陷）

- **本轮复盘结论**：R2 完成。自查发现：库对话框（历史/模板）**只能从浮窗进入**；浮窗关着时用户想翻历史/模板
  必须先热键唤起浮窗再点按钮。托盘菜单只有 显示/设置/退出，缺这条路径。
- **下一步方向及优先级**：R4 托盘划词开关（中）。
- **本轮执行结果**：
  - `_build_tray(..., open_library=None)` 新增「历史与模板库」菜单项，`main()` 传 `overlay._on_open_library`。
  - `overlay._on_library_load`：加载历史/模板时若浮窗隐藏，先 `show_at_cursor()+activateWindow()` 把浮窗带出来
    ——否则「从托盘加载了但看不到」，等于点了没反应。
  - **意外收获（真实缺陷）**：为该菜单写测试时发现托盘菜单项**全部失效**。定位：`QAction("显示（热键）")`
    等只被函数内局部变量引用，`_build_tray` 返回后引用计数归零 → QAction 被回收 → 托盘右键菜单变成
    **空菜单**（用户点右键什么都看不到）。实验对照（保留引用 / `addAction(str)` / **挂 parent=menu**）确认
    第三种最省事且可靠；已给全部 4+1 个 QAction 挂 `parent=menu`。全仓检索确认 `QAction/QMenu` 仅在 `app.py` 一处使用。
  - 验证：`test_ui_smoke` 新增 `[ok] 19b`（托盘菜单 ≥4 项 + 「历史与模板库」触发回调 + 气泡点击仍在）、
    `[ok] 19c`（隐藏浮窗加载后被带出）；测试内**显式 `gc.collect()`** 以真正卡住这类「被回收」缺陷。**通过**。
  - 来源：PySide6 对象所有权（C++/Python）语义；本项目 `_build_tray` 实测。
- **遗留问题**：无（菜单项已于真机可验，但托盘实际外观仍需真机看一眼——标注待确认）。

---

## R4 — 托盘「划词自动弹工具条」开关（免开设置面板）

- **本轮复盘结论**：R3 完成。写文档/写代码时划词工具条会频繁弹出打断，此前只能「打开设置→取消勾选→保存」四步；
  高频操作应该有一步入口。
- **下一步方向及优先级**：R5 设置面板「恢复默认」（中）。
- **本轮执行结果**：
  - `_build_tray(..., cfg=None)` 新增可勾选菜单项「划词自动弹工具条」：勾选态 = `config.selection_toolbar`；
    切换即写配置 + 落盘 + 气泡提示「已启用/暂停」。
  - `menu.aboutToShow` 时同步一次勾选态（`blockSignals` 防误写）——设置面板里改过也能对齐，且**不会**反向写配置。
  - 与既有链路天然打通：`SelectionMonitor(enabled_getter=lambda: cfg.get("selection_toolbar", True))` 与
    `on_selection` 的首行判断都实时读该配置，无需重启或重建监听器。
  - 验证：`test_ui_smoke` 新增 `[ok] 19d`——初始勾选态与配置一致、取消勾选写入配置并落盘、
    `aboutToShow` 同步外部改动且**不**产生多余写盘。**通过**。
  - 来源：同类工具（PopClip/Raycast）均提供「暂停」快捷开关的交互惯例。
- **遗留问题**：无。

---

## R5 — 设置面板「恢复默认」+ 顺带修掉热键默认值的「不规范」隐患

- **本轮复盘结论**：R4 完成。用户一旦把温度/超时/热键/模板改乱，只能手改 `config.json` 或凭记忆逐项改回；
  面板缺一个「恢复默认」。另在做该功能时撞见一处**真实隐患**（见下）。
- **下一步方向及优先级**：R6 首次运行引导（中）。
- **本轮执行结果**：
  - `config.reset_to_defaults(data, keep=("api_keys","custom_providers"))`：**纯函数**，重置设置项、
    保留用户数据（自定义端点、旧 api_keys 字段）；不落盘，便于单测。
  - `settings_dialog`：按钮区（ResetRole）新增「恢复默认」→ 确认后把**控件**置为默认值（**不落盘**，
    需再点「保存」生效，可「取消」放弃）；保留自定义端点/钥匙串 Key。
  - **顺带修复（真实隐患）**：`DEFAULT_CONFIG["hotkey"]` 原为 `<ctrl>+<shift>+space`（**bare "space"**，
    非 `validate_hotkey` 的规范输出 `<space>`）。`app.py` 里「校验失败时的回退字面量」也用的这个 bare 写法
    ——而 R1 的 `parse_combo` 只认规范格式 → **回退值本身会被判非法，热键完全不注册**。
    已统一：默认值/两处回退字面量都改为规范格式；占位提示改为更友好的 `Ctrl+Shift+Space / Ctrl+Alt+K`。
  - 验证：`test_ui_smoke` 新增 `[ok] 8c`——纯函数（重置设置项 + 保留自定义端点/api_keys）+ UI
    （控件回默认、**未点保存不落盘**、保存后落盘、自定义端点仍在）双段断言。**通过**。
  - 来源：本仓 `validate_hotkey`/`parse_combo` 语义一致性检查。
- **遗留问题**：`config.json` 里存量用户的 hotkey 若为 bare 写法，仍会被 `app` 侧 `validate_hotkey` 归一化，
  不影响功能（已确认调用点）。

---

## R6 — 首次运行引导（新装用户「一优化就失败」）

- **本轮复盘结论**：R5 完成。新装/新配置环境下 provider 默认 deepseek（**需要 Key**），但配置里没有 Key；
  用户第一次点「优化」只会得到一句 `未配置 API Key —— 点右上角「设置」`——**失败前置、体验劝退**。
  全仓检索确认此前**没有任何首次运行引导**。
- **下一步方向及优先级**：R7 启动性能（中）。
- **本轮执行结果**：
  - `util.should_guide_first_run(cfg_data, needs_key, has_key)`：**纯函数**判定（未跑过引导 + 需要 Key + 确实没 Key）。
    Ollama（`needs_key=False`）与已配 Key 的老用户都不会被打扰。
  - `config.DEFAULT_CONFIG["first_run_done"] = False`（装一次只引导一次）。
  - `app.main()`：启动尾部判定，命中则状态栏给出三条出路（填 Key / 切 Ollama 本地 / 先用零成本「本地整理」），
    并 `QTimer.singleShot(800, open_settings)` 把设置面板**主动带到面前**；同时把 `first_run_done` 置位落盘。
  - 验证：`test_ui_smoke` 新增 `[ok] 8d` 四态断言（需Key+无Key→引导；有Key→不打扰；Ollama→不打扰；
    已跑过→不再引导）。**通过**。
  - 来源：通用首启引导惯例 + 本仓 `overlay._on_optimize` 的「未配置 API Key」早退分支。
- **遗留问题**：`open_settings` 用 800ms 延迟弹出——真机需确认不会与浮窗首帧抢焦点（离屏无法验，标注待确认）。

---

## R7 — 启动关键路径不加载 keyring（惰性加载名不副实 → 真的惰性）

- **本轮复盘结论**：R6 完成。用 `-X importtime` 量化启动导入：`import promptpop.app` 共 0.707s，
  其中 **`keyring` 一项占约 0.28s（导入树）**，是本项目最贵的单个依赖。而 `secrets.py` 顶部写着
  「keyring 为**惰性导入**」，实际是「模块顶层 try-import」（只防了 ModuleNotFoundError，**并未惰性**）——
  **注释与实现不符**；且 `app.main()` 每次启动都无条件调 `migrate_plaintext_to_keyring`，
  等于为一次「通常无事可做」的迁移在启动关键路径上加载 0.4s 的依赖。
- **下一步方向及优先级**：R8 独立代码审查（中）。
- **本轮执行结果**：
  - `secrets.py` 重写为**真惰性**：`_kr()` 首次调用才 `import keyring` 并缓存；`backend_available/get_key/set_key`
    全部改走 `_kr()`；缺 keyring 仍安全降级（返回 False/""）。
  - `app.main()`：迁移加前置守卫 `if any((cfg.get("api_keys") or {}).values())`——**只有真的还留着明文 Key
    才加载 keyring**。绝大多数启动（早已迁移完）完全不碰它。
  - 验证：①新进程 `import promptpop.app` 后 `'keyring' in sys.modules` 为 **False**（`test_ui_smoke` 新增
    `[ok] 8e`，子进程实测）；②`test_cycle6` 的惰性断言改用 `_kr()` 入口并仍通过；
    ③`test_rounds`（走 `migrate_plaintext_to_keyring` 真实路径）通过。
  - 实测：`import promptpop.app` 由 **0.707s → 约 0.57–0.61s**；对照实验（`keyring+app` vs `app`）
    显示 keyring 在本上下文的边际成本约 **0.10–0.15s**（独立导入约 0.41s，与 Qt 已载模块部分重叠）。
    增益不大但**零风险**，且修掉了「注释说惰性、实现不惰性」的名实不符。
  - 来源：`python -X importtime` 实测 + keyring 官方文档（backend 发现机制会遍历入口点，是其导入偏重的原因）。
- **遗留问题**：设置面板首次打开时会有一次 keyring 导入（约 0.1–0.4s，视后端）——属可接受的一次性成本，
  已从「每次启动」转移到「首次用到」。

---

## R8 — 独立代码审查（第三方视角）+ 自查修复

- **本轮复盘结论**：R7 完成。按前两轮惯例，本轮做一次**独立审查**（交给独立 reviewer 通读 R1–R7 改动，
  重点：Windows API 用法、Qt 对象所有权、线程/生命周期、测试有效性）。同时我自己先按同一清单自查。
- **下一步方向及优先级**：R9 落地修复 + 回归工具化（高）。
- **本轮执行结果（自查部分，先行落地）**：
  - **真缺陷（R2 引入，自查发现）**：`settings_dialog._save()` 把热键「试注册」放在 `config.save()` **之后**——
    注册失败时磁盘已写过一次，再回滚 hotkey 又写一次；此时若用户点「取消」，`reject()` **只回滚内存不回滚磁盘**
    → 内存与磁盘不一致（用户以为取消了，重启后设置却变了）。**修法**：把试注册**提到所有落盘之前**，
    失败即整体放弃（磁盘/内存都不动），并把输入框退回实际生效的旧组合。
    验证：`test_ui_smoke` `[ok] 8b` 强化断言——**失败时 `save()` 一次都没调用**、输入框已退回旧值。
  - 契约一致性：新增往返测试（266 个 `validate_hotkey → parse_combo` 组合全部可解析），
    防止两侧映射表（`util._KEY_MAP` vs `hotkey._VK`）今后各自演化时出现「用户填了合法热键却注册失败」。
  - 清理：`_VK` 里一个笔误产生的死键（`` `<` ``）已删除。
  - 自查确认**不成立**的担忧（记录以免后续重复怀疑）：`WinHotkeyManager` 在真实 app 里**只创建一次**
    （`main()` 里 `bridge = create_hotkey_manager()`），测试里多次创建产生的重复 event filter 不进生产路径。
- **独立审查结论（3 条真缺陷 + 若干加固项，逐条已处理，详见 R9）**：
  - **真缺陷 A（打中 R3 的修复本身）**：`overlay._on_library_load` 的「把隐藏浮窗带出来」在**真实模态路径上从不生效**。
    机制：库对话框是「**先 emit `load_requested`、再 `accept()`**」（`library_dialog.py:111-112/246-247`），
    回调执行时弹窗仍开着、`_active_dialog` 仍指向它 → `show_at_cursor()` 命中「有活动弹窗只把弹窗提前」的守卫
    直接 return → 浮窗根本没 show；随后 accept() 关掉库窗口，浮窗依旧隐藏。**等于我的修复是空转**。
    我的测试 19c 直接调 `_on_library_load`（无活动弹窗）→ 通过，但**绕过了真实模态路径**，测不出该缺陷。
  - **真缺陷 B**：`util.validate_hotkey` 与 `hotkey.parse_combo` 规则不一致。validate 只要求「≥2 段」，
    **既不要求有修饰键也不要求有主键**（与自身 docstring 矛盾）；parse 强制「有修饰键 + 有主键」。
    → `Ctrl+Shift`、`A+B`、`F1+F2` 这类输入在设置里显示**绿色「可用」**、`check_hotkey_risk` 也不拦，
    保存后实际注册失败（走 `hotkey_changed` 兼容路径时甚至被静默落盘）。我的往返测试只覆盖「修饰键+主键」，
    所以没抓到。
  - **真缺陷 C**：`settings_dialog._save()` 热键试注册在 `config.save()` 之后 → 失败时磁盘已写过，
    用户再点「取消」会内存/磁盘分叉（**我在自查中已先行发现并修掉**；reviewer 独立命中同一条，互为交叉验证）。
  - **加固项**：`WinHotkeyManager` 从不 `removeNativeEventFilter`（生产只建 1 个，但测试同进程建 6 个会累积）；
    `_id` 硬编码为 1；`restart_hotkey` 的 `prev != new_combo` 守卫在 `prev == new` 时会漏掉回滚（热键彻底消失）；
    `_VK` 死键；`set_key(provider,"")` 删除失败仍返回 True；测试 `test_hotkey` mock 还原无 try/finally；
    `test_cycle6.test_secrets_lazy_import` 断言藏在 `if kr is None:` 里（装了 keyring 的机器上整段被跳过=空洞）。
  - **审查确认「不成立」的担忧**（记录以免重复怀疑）：`nativeEventFilter` 的 eventType/返回值/`singleShot(emit)`/
    `wParam` 比较均正确；`secrets` 惰性改造正确且降级安全；`first_run_done` 先落盘再弹窗正确；
    `_build_tray` 的 QAction parent 修复完整、其它无 parent 的 QObject 均被栈帧/闭包持有。
- **遗留问题**：`QTimer.singleShot(800, open_settings)` 与浮窗首帧抢焦点需真机确认。

---

## R9 — 回归工具化：一条命令跑全部 + 每文件硬超时

- **本轮复盘结论**：R8 自查修复完成。**本轮最大隐性成本**是回归本身：用 shell 循环跑 11 个测试文件时，
  已**两次**出现外层 subshell/管道卡死（实际单个文件只需 0.3–9s），排查成本高于修 bug 本身。
- **下一步方向及优先级**：R10 收尾（版本号/打包/记录）。
- **本轮执行结果**：
  - 新增 `tests/run_all.py`：每个测试文件**独立进程 + 180s 硬超时**，逐文件汇总（状态/耗时/末行），
    任一失败或超时以非零码退出。挂住的文件被标 TIMEOUT 后继续往下跑，不再拖死整条回归。
  - 实测：**11 个文件全 OK，总耗时 31.0s**（`ui_smoke` 2.2s / `cycle3` 8.8s 为最慢），
    同时反证此前两次「卡死」是 shell 循环的假象（`test_threads` 实测 0.7s）。
  - 来源：本项目两次卡死经历 + 各测试文件在模块级创建 QApplication、无法同进程收集的既有约束。
- **遗留问题**：无（后续回归建议统一走 `python tests/run_all.py`，不要再写 shell 循环）。

---

## R9（续）— 落地独立审查的 3 条真缺陷 + 加固；**并揪出此前两次"回归挂死"的真凶**

- **本轮复盘结论**：R8 的独立审查交出 3 条真缺陷（见上）。逐条落地。
- **下一步方向及优先级**：R10 收尾（打包 v0.7.5）。
- **本轮执行结果**：
  1. **真缺陷 A 修复**：`_on_library_load` 改为 `QTimer.singleShot(0, self._show_after_library_load)` ——
     把显示排到本轮事件处理之后（那时库对话框已关、`_open_modal` 的 finally 已把 `_active_dialog` 置 None，
     守卫自动放行）。测试 19c 改写为**真实模态路径**：显式 `modal.show()` + 置 `_active_dialog`，
     断言①模态期间浮窗不显示②解除模态后 `processEvents()` 浮窗必须出现。
     （关键：测试里 modal 必须**真的可见**，否则守卫会放行 → 变成假阳性。旧代码在此测试下必失败。）
  2. **真缺陷 B 修复**：`validate_hotkey` 增加「至少 1 个修饰键 + 至少 1 个主键」两条检查，与 `parse_combo` 严格对齐；
     往返测试扩充退化输入（`Ctrl+Shift`/`A+B`/`F1+F2`/`Space` 等 6 例，两侧必须**一致拒绝**）。
  3. **真缺陷 C**：已在 R8 自查中修复（试注册前置到落盘之前），本轮补强断言（失败时 `save()` 零调用）。
  4. **加固**：`hotkey._id_seq` 全局自增（不再硬编码 1）；新增 `dispose()`（注销 + `removeNativeEventFilter`），
     `aboutToQuit` 改连 `dispose`；`restart_hotkey` 抽成 `app.make_hotkey_restarter(bridge, state)` 并**无条件回滚**
     （去掉 `prev != new_combo` 守卫）；`secrets.set_key(prov,"")` 删除失败改为返回 False；清理 `_VK` 死键。
  5. **测试补强**：新增 `[ok] 20b`（热键切换回滚语义，含 `prev == new` 边界）；
     `test_hotkey` 的 mock 还原加 `try/finally`（避免断言失败污染后续用例）；
     `test_cycle6` 的 secrets 断言去空洞化（必检项 + 无后端降级分支）。
  6. **★ 揪出「回归挂死」真凶**：本轮全量回归时 `test_threads.py` **真的超时 180s**（此前只需 0.8s）。
     根因是**测试自身死锁**：`_ForeverThread` 让 `run()` 跨整个 while 循环持有非递归 `QMutex`，
     而 `stop()` 也去抢同一把锁 → 谁先抢到决定生死（主线程先抢=通过、worker 先抢=**永久死锁**）。
     已用独立最小实验复现该阻塞模式；修复改用 Qt 惯用的 `requestInterruption()/isInterruptionRequested()`
     （不再跨循环持锁）。
     **修正此前判断**：R7/R9 前两次把同类挂死归因为「shell 循环/管道假象」是**误判**——真凶就是这个随机死锁，
     "前台逐文件秒级全过"只是因为每次跑都恰好抢锁赢。
  7. 验证：`test_threads` **连续跑 25 次，0 失败 0 超时**（总 19.4s，均 0.78s/次）；
     全量 `run_all.py` **11/11 全绿、总 32s**。
  - 来源：独立审查清单（本轮）+ `QMutex` 非递归语义（Qt 文档）+ 最小复现实验。
- **遗留问题**：`_ForeverThread` 这类「测试自身写错」的问题说明测试也需要 review——后续轮次建议把
  「新写测试是否能测出目标缺陷（反向验证）」作为固定动作。

---

## R10 — 收尾：版本号 / 冻结 exe / 全量回归 / 记录

- **本轮复盘结论**：R1–R9 全部完成，独立审查 3 条真缺陷已落地，全量回归 11/11 绿。
- **下一步方向及优先级**：10 轮目标达成；下轮候选（按优先级）：①「取词真实覆盖率」真机数据采集
  （UIA vs 剪贴板的命中率统计，需真机）；②设置面板「热键录制控件」（按键即录，替代手打）；
  ③「新写测试的反向验证」纳入固定动作（用旧代码跑新测试，必须失败）。
- **本轮执行结果**：
  - `version_info.py` → **0.7.5.0**；`PromptPop-onefile.spec` 冻结成功 → `C:/Users/y/Desktop/PromptPop.exe`
    （**58.0MB**，FileVersion/ProductVersion 均为 0.7.5.0）。
  - 启动存活验证：进程存活 6s+，真实 app 子进程工作集 ~145MB（PySide6 GUI 已完整加载，非引导器空转）。
  - **踩坑记录（本轮新增）**：onefile 的 `Start-Process -PassThru` 拿到的是**引导父进程**，
    真正 app 是它的**子进程**；只杀父进程会留下孤儿（上一轮「孤儿进程占单实例锁、导致 test_cycle2 误报回归」
    就是这个坑）。**正确姿势：验证与清理都按进程名做**，杀完确认无残留。
  - 最终回归：`python tests/run_all.py` → **11/11 全绿，总 32s**。
- **遗留问题（待真机确认，离屏不可验）**：
  1. 原生热键在 **Chrome / VS Code / 微信** 等焦点下是否确实比 pynput 稳（机制上由 OS 派发、不依赖钩子，但需实测）；
  2. 首次运行引导的 `QTimer.singleShot(800, open_settings)` 是否与浮窗首帧抢焦点；
  3. 取词覆盖率（UIA/剪贴板兜底）——沿用前两轮结论，仍需真机数据。

---

## 本轮 10 轮汇总（v0.7.5）
- **R1**：全局热键改 Windows 原生 `RegisterHotKey`（新增 `hotkey.py`）。
- **R2**：热键注册失败可见 + 保留旧热键 + 不关窗。
- **R3**：托盘补「历史与模板库」入口；**并修掉托盘菜单被 GC 成空菜单的真缺陷**。
- **R4**：托盘「划词自动弹工具条」开关。
- **R5**：设置「恢复默认」；**并修掉默认/回退热键写法不规范导致热键完全不注册**。
- **R6**：首次运行引导。
- **R7**：启动关键路径不加载 keyring（0.707s → 0.57s）。
- **R8**：独立审查（3 条真缺陷 + 若干加固项）。
- **R9**：落地审查修复；回归工具化 `run_all.py`；**揪出「回归挂死」真凶（测试自身 QMutex 死锁）**。
- **R10**：版本 0.7.5.0 + 冻结 exe + 全量回归 + 记录。
- **验收**：`tests/run_all.py` **11/11 全绿（32s）**；新增 1 个测试文件（`test_hotkey.py`）+ 1 个工具（`run_all.py`），
  扩展 `test_ui_smoke` 6 项、`test_cycle6` 1 项；**5 个真缺陷修复**（托盘空菜单 / 热键回退值非法 /
  保存失败致内存磁盘分叉 / 热键规则不一致致"显示可用却注册失败" / 库加载在模态路径空转）+ 1 个测试死锁。
- **产物**：`C:/Users/y/Desktop/PromptPop.exe`（v0.7.5.0，58.0MB，启动存活验证通过）。
