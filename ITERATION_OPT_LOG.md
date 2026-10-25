# PromptPop 体验优化迭代日志（10 轮循环 · 2026-10-14）

> 目标：在 v0.7.2 基础上继续找问题、提升体验；每轮结合软件内自查 + 网络/GitHub 调研。
> 调研依据：独立调研报告（同类工具 PopClip/Raycast/QDuo/AIA-selection-assistan、PySide6 置顶窗坑、全局热键 RegisterHotKey 最佳实践、跨应用取词/回填三路降级、httpx/LLM 流式重试与取消）。
> 验收以离屏 UI 冒烟测试 + 纯函数单测 + 代码审查为主；纯真机项标注「待确认」。

---

## R1 — 热键注册失败可见化 + 自定义热键风险校验
- **本轮复盘结论**：v0.7.2 热键用 pynput `GlobalHotKeys`；但注册失败时（`_start_hotkey` 返回 None）状态栏仍谎称「热键 X 唤起」，用户无法察觉失灵。自定义热键也无任何冲突/系统保留校验。
- **下一步方向及优先级**：R2 剪贴板还原保真（高）；R3 划词监听降噪（高）。
- **本轮执行结果**：
  - `util.check_hotkey_risk(combo)`：拦截 Windows 系统占用的 Win+ 组合（Win+L 锁屏等，注册也收不到），对含 Space 的组合（Ctrl+Shift+Space，易与输入法冲突）给出非阻断风险提示。
  - `settings_dialog._save`：保留组合直接拦保存；易冲突组合弹提示仍放行。
  - `app.main`：用 `hotkey_state["active"]` 如实反映注册状态——失败则状态栏改提示「请用托盘菜单唤起」，不再谎报。
  - 验证：`test_cycle5` 新增 `test_hotkey_risk`（保留/易冲突/普通/空 4 类断言）通过；全量回归前 7 套绿，test_ui_smoke 进行中。
  - 来源：调研报告第 2 类（RegisterHotKey 系统保留键黑名单、Ctrl+Shift+Space 高风险）。
- **遗留问题**：pynput 仍是线程钩子方案，未改 RegisterHotKey（风险高、且当前可用，暂不换）；热键失败仅状态栏提示，未弹一次性引导。

---

## R2 — 剪贴板还原保真（完整 MIME 快照）
- **本轮复盘结论**：R1 完成。核查 `capture.extract_clipboard`：取词前仅备份 text+html，取词结束还原，但 Office 等会往剪贴板放私有格式，只还原 text+html 会丢失/损坏这些格式（调研第 3 类明确警告）。
- **下一步方向及优先级**：R3 划词监听降噪（高）；R4 输入超长防护（高）。
- **本轮执行结果**：
  - `capture._clipboard_snapshot()`：完整克隆当前剪贴板所有 MIME 格式（含 Office 私有格式/图片）为 QMimeData；`extract_clipboard` 在 `finally` 用 `_clipboard_restore_full` 原样还原，快照失败时回退 text+html。
  - 验证：`test_ui_smoke` 新增 `test_clipboard_snapshot_restore_fidelity`（用 fake clipboard 隔离，断言自定义格式在改写→还原后不丢）。离屏 QClipboard 不可靠，故用 fake 隔离测试克隆逻辑。
  - 来源：调研报告第 3 类（Office 私有格式崩溃/损坏风险，需保存/恢复所有格式）。
- **遗留问题**：快照/还原的真实跨格式保真需真机验证（离屏测的是克隆逻辑）；极端情况下 QMimeData 某些格式 `data()` 不可克隆已被 try 包裹。

---

## R3 — 划词监听降噪（程序黑名单）
- **本轮复盘结论**：R2 完成。核查 `SelectionMonitor`：任何左键拖拽都触发取词→剪贴板抖动/工具条误弹（如 Explorer 拖文件、窗口标题栏拖拽）。
- **下一步方向及优先级**：R4 输入超长防护（高）；R5 错误反馈升级（中）。
- **本轮执行结果**：
  - `config` 新增 `selection_exclude_programs`（默认 `["explorer","dopusrt","dllhost"]`）；`capture.should_capture_selection(program, exclude)` 纯函数：这些程序里「拖拽」多为移动文件/窗口，跳过取词。
  - `app.on_selection` 在取词前先判黑名单；`config.migrate` 自动补默认键（幂等）。
  - 验证：`test_cycle5` 新增 `test_should_capture_selection`（大小写/子串匹配）+ `test_config_migrate_keeps_new_keys`。
  - 来源：调研报告第 1 类 #5（避免常驻打扰，「宁可多一步不可打断用户」）。
- **遗留问题**：滚动条/窗口标题拖拽（非黑名单程序内）仍可能偶发误触发（无选中则取词返回空、不弹，危害低）；后续可加光标形状二次判定。

---

## R4 — 输入超长防护（可配置上限）
- **本轮复盘结论**：R3 完成。核查：优化/迭代提交无长度上限，超长输入会撑爆上下文、产生巨额账单（调研第 5 类建议 MAX_REQUEST_TOKENS 预算拦截）。
- **下一步方向及优先级**：R5 错误反馈升级为可见横幅（中）；R6 多提供商扩展（中）。
- **本轮执行结果**：
  - `config` 新增 `max_input_chars`（默认 20000，0=不限制）；`overlay._on_optimize` / `_on_iterate` 提交前校验，超限状态栏明确提示「过长/上限/请精简分段」并拦截。
  - `settings_dialog` 新增「单条输入上限(字)」字段，校验为非负整数。
  - 验证：`test_cycle5` 迁移测试已含新键；overlay 守卫走代码审查（提交拦截逻辑纯文本校验，离屏单测成本高，标注待确认）。
  - 来源：调研报告第 5 类 #6（调用前预算拦截超长输入防爆单）。
- **遗留问题**：超限拦截为「硬拦」，未提供「仍要提交」选项；字符数≠token 数（中文 1 字≈1-2 token），阈值偏保守，可按需放宽。

---

## R5 — 错误反馈升级（状态栏颜色分级）
- **本轮复盘结论**：R4 完成。核查：失败/取消/成功都挤在底部一行 `QLabel`，颜色无区分，失败易被忽略（如「失败：401」混在普通信息里）。
- **下一步方向及优先级**：R6 多提供商扩展（中）；R7 检查更新（中）。
- **本轮执行结果**：
  - `overlay._status(msg, kind)` 新增 `kind`：error=红(#e06c5a)、warn=黄(#c9a227)、ok=绿(#5b9e5b)、info=主题默认色；失败/取消/超长/缺Key/Ollama未运行 用对应级别。
  - 验证：`test_ui_smoke` 新增 `test_status_color_levels`（四级别颜色断言）。
  - 来源：通用 UX 最佳实践（错误需显式、可辨，避免静默失败）。
- **遗留问题**：未做独立「错误横幅」浮层（颜色分级已满足区分需求，加浮层改动大、收益边际，暂不做）。

---

## R6 — 多提供商扩展（自定义 OpenAI 兼容端点）
- **本轮复盘结论**：R5 完成。核查 `providers.PROVIDERS` 硬编码 3 家，用户若用 OpenRouter/本地 vLLM/自建网关无法接入，只能改源码。
- **下一步方向及优先级**：R7 检查更新（中）；R8 取词阻塞缓解（中）。
- **本轮执行结果**：**调研结论：OpenAI 兼容协议已统一 `base_url+key`**，扩展成本极低。计划：设置新增「自定义端点」——名称+base_url+模型，写入 config 的 `custom_providers` 列表，下拉合并内置项；`providers.resolve` 优先查自定义。验收：配置读写 + 下拉动态 + 纯函数单测。
  - （实现中：providers.py 增加自定义端点解析；settings_dialog 增加增删 UI；overlay 下拉数据源合并；test 验证。）
  - 来源：调研报告第 6 类（AIA-selection-assistan 多 API 模板 + 归一化 Base URL）。
- **遗留问题**：自定义端点暂不校验可达性（由现有 PingThread 测活覆盖）；UI 增删交互需真机确认易用性。

---

## R6b（原 R7「检查更新」改向）
- **决定**：取消「GitHub releases 检查更新」——PromptPop 未发布到 GitHub，无真实 release 源，该功能只会 404 误导。改为 R7=二次独立审查找新问题（更高价值，见下）。
- **理由**：无法验证/必然失败的方向不做（遵循「避免无效探索、无法验证须标注」）。

---

## R8 — 取词阻塞缓解（延时可配置 + 短窗口去重）
- **本轮复盘结论**：R6b 决定改向。核查 `extract_clipboard`：在主线程 `time.sleep(0.12~0.28)` 最多两次，冻结事件循环（调研第 4 类 QClipboard 线程限制 + 第 1 类「宁可多一步不可打断」）。
- **下一步方向及优先级**：R7 二次独立审查 + 修复（高）；R9 键盘可达性（低）。
- **本轮执行结果**：
  - `capture.pick_clipboard_delay(program, cfg)` 纯函数：默认延时 / 慢程序延时可经 `clipboard_delay_default` / `clipboard_delay_slow` 配置（默认值不变，避免回归），`extract_clipboard` 改用它。
  - `app.on_selection` 加 300ms 同坐标去重：连续在同一处拖选不重复取词，避免主线程冻结叠加。
  - 验证：`test_cycle5` 新增 `test_pick_clipboard_delay`；`test_config_migrate_keeps_new_keys` 纳入新键。
  - 来源：调研报告第 4 类（QClipboard 须主线程）/ 第 1 类 #5（避免打扰）。
- **遗留问题（待真机确认）**：UIA 失败走剪贴板回退时仍有 ~0.12s 主线程阻塞（QClipboard+SendInput 时序固有，无法完全消除）；延时调低可能降低慢程序取词成功率，已保留保守默认值。

---

## R9 — 对话框键盘可达性
- **本轮复盘结论**：R8 完成，全量回归 7/8 通过，test_cycle4 曾出现「QThread destroyed while running」——单独/连跑 3 次均稳定 OK，判定为并行跑套件时的进程退出噪声，非确定性回归（已记录，不修改）。
- **下一步方向及优先级**：R7 二次独立审查 + 修复（高）；R10 收尾打包。
- **本轮执行结果**：
  - `overlay._on_diff` 差异视图：关闭按钮设为 default（Enter 关闭），新增「复制差异」按钮（Ctrl+C 被浮窗全局快捷键占用，改用按钮）。
  - `library_dialog`：「关闭」设为 default 按钮。
  - 验证：`test_ui_smoke` 新增 `test_dialogs_have_default_button`（默认按钮存在 + reject 关闭）。
  - 来源：通用 UX（键盘可达性 / WCAG 焦点顺序）。
- **遗留问题**：Esc 依赖 QDialog 默认 reject 行为，未显式覆写 keyPressEvent（当前行为已正确，加覆写反而冗余）。

---

## R7 — 二次独立审查 + 修复（已完成）
- **本轮复盘结论**：R9 完成。派独立审查者对 R1-R6 后代码二次审查，返回 **14 条**（1 必崩 + 6 功能失效 + 7 健壮性/体验）。
- **下一步方向及优先级**：R10 收尾打包（高）。
- **本轮执行结果**（逐条处置）：
  - **#1 必崩（已修）**：`settings_dialog.closeEvent` 原会把 `_ping_thread` 置 None → 释放运行中 QThread 的最后一个引用 → abort。改为只断开信号；`_on_ping` 加 `finished→deleteLater`；`_on_ping_result` 不再 deleteLater。
  - **#2（已修）**：`app.on_selection` 原不记录来源窗口 → 工具条「优化」时前台已是浮窗自己。新增 `toolbar.source_hwnd`（on_selection 存 fg），`toolbar_optimize` 优先用它，取不到再退回 `_pick_owner_hwnd()`。
  - **#3（已修）**：`set_input` / `_on_library_load` 硬编码 `[:8000]` 截断且无提示 → 改遵循 `max_input_chars` 配置，截断时状态栏 warn 提示。
  - **#4（已修）**：A/B 评估在浮窗隐藏时结果永久丢失 → 新增 `_pending_judge`，`show_at_cursor` 显示后补弹 `ScrollableResultDialog`。
  - **#5（已修）**：设置「取消」不撤销端点增删（后续任意 save 会静默落盘）→ `SettingsDialog.__init__` 深拷贝快照 `config.data`，`reject()` 还原。
  - **#6（已修）**：`insert_after` 无选区时发 Right 键导致光标偏移一位 → 新增 `_has_text_selection()`（UIA best-effort，探测失败保守返回 True），无选区则直接粘贴。
  - **#7（已修）**：替换/插入恒返 True 的假成功 → `_send_ctrl_v()` 后 sleep 0.12s 再 `GetForegroundWindow() == owner_hwnd` 校验，不符返回 False 走「已复制」分支。
  - **#8（已修，最高危且低成本）**：`secrets.py` 顶层硬 `import keyring`，而 requirements.txt 未声明 → 全新环境启动即崩。改惰性导入，无 keyring 时 `set_key` 返回 False、回退 config 明文。
  - **#9（部分/标注）**：取词主线程 sleep 0.24~0.56s 冻结——QClipboard+SendInput 时序固有，R8 已把延时改为可配置并加 300ms 去重；根治需改信号驱动（`QClipboard.changed`/`ClipboardSequenceID`），**待真机验证后评估**。
  - **#10（已修）**：Ollama 探测每次同步阻塞满 3s → 加 10s TTL 缓存（只缓存「可达」，不可达不缓存以便尽快恢复）。
  - **#11（已修）**：配置损坏即静默全重置 + 非原子单备份 → `load` 损坏时从 `.bak` 恢复；`save` 改「临时文件 + `replace`」原子写。
  - **#12（已修）**：Key 保存失败被静默忽略 → `_save` 检查 `secrets.set_key` 返回值，失败即警告并阻止 accept。
  - **#13（已修）**：工具条无手动关闭、失焦不收起 → 补 ✕ 按钮 + `changeEvent` 失焦即 hide + `hideEvent` 停定时器。
  - **#14（已修）**：ModelFetcher 无 `finished→deleteLater`（与 PingThread 收尾不统一）→ 补上，统一生命周期模式。
  - 验证：`test_cycle6` 新增 4 项（secrets 惰性/config 原子+恢复/ollama 缓存/自定义端点）；`test_ui_smoke` 新增 4 项（关闭不断 ping 引用/工具条记来源窗口/设置取消还原快照/输入守卫三入口）。全量 8 套回归绿。
- **遗留问题**：#9 取词主线程冻结未根治（待真机）；审查另提「`open_settings` 中 dlg 为局部变量，exec 返回即销毁，ping 仍在飞行中时仍有析构风险」——建议真机验证「测试连接→立即关闭设置」，最稳收尾是 closeEvent 里 `th.quit(); th.wait(3000)`（我评估后认为 wait 会阻塞 UI 线程 3s，权衡暂不加，标注待确认）。

---

## R10 — 收尾：全量回归 + 打包 v0.7.3 + 日志汇总（进行中）
- **本轮复盘结论**：R7 完成（14 条审查问题：12 条已修、1 条部分修、1 条权衡不加）。版本号已升 0.7.3，README 已更新，requirements.txt 补 keyring 声明。
- **下一步方向及优先级**：等最终回归结果 → 打包 → 桌面 exe → 启动核验 → 记大脑。
- **本轮执行结果**：最终回归进行中；打包待回归通过后执行。
- **遗留问题**：见下「总结与遗留」。

---

## 总结（10 轮）

**完成度**：10 轮全部执行（R1-R10），其中 R6b/R7 有方向调整（记录在案）。

| 轮次 | 主题 | 状态 |
|---|---|---|
| R1 | 热键注册失败可见化 + 自定义热键风险校验 | ✅ |
| R2 | 剪贴板还原保真（完整 MIME 快照） | ✅ |
| R3 | 划词监听降噪（程序黑名单） | ✅ |
| R4 | 输入超长防护（可配置上限） | ✅ |
| R5 | 错误反馈升级（状态栏颜色分级） | ✅ |
| R6 | 多提供商扩展（自定义 OpenAI 兼容端点） | ✅ |
| R6b | 「检查更新」→ 取消（无真实 release 源，必然失败） | 记录在案 |
| R7 | 二次独立审查 + 修复（14 条：12 修/1 部分/1 权衡） | ✅ |
| R8 | 取词阻塞缓解（延时可配置 + 300ms 去重） | ✅ |
| R9 | 对话框键盘可达性（默认按钮/ Esc/ ✕） | ✅ |
| R10 | 收尾打包 v0.7.3 | 进行中 |

**测试增量**：新增 `test_ui_smoke` 17 项、`test_cycle5` +4 项、`test_cycle6` +5 项；8 套回归全绿。

**仍待真机确认**：
1. 浮窗快捷键实机响应（Ctrl+D/I/R/Shift+C）。
2. 替换/插入焦点命中率（#7 新增粘贴后前台校验）。
3. 取词主线程瞬时阻塞（#9，仅 UIA 失败走剪贴板回退时）。
4. 「测试连接 → 立即关闭设置」的 QThread 析构（#1 遗留注意）。
5. 自定义端点 UI 增删易用性、A/B 隐藏后补弹。





