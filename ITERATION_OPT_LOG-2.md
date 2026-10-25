# PromptPop 体验优化迭代日志 · 第二轮 10 轮循环（v0.7.4）

> 目标：延续第一轮，对 v0.7.3 继续「找问题→改→验证」；仍以调研 + 自查双轮驱动。
> 输入：第一轮遗留（R7 #1 QThread 析构风险、R7 #9 取词主线程冻结、5 项待真机确认）。
> 验收：离屏 UI 冒烟 + 纯函数单测 + 代码审查；纯真机项标注「待确认」。

---

## R1 — QThread 生命周期：模块级注册表（修 R7 #1 遗留）
- **本轮复盘结论**：第一轮 10 轮完成、v0.7.3 已发布。遗留最高危项：`open_settings` 的 `dlg` 是 `exec()` 返回即析构的局部对象，ping 飞行中随对话框释放的引用一没，运行中 QThread 被 GC → 进程 abort。v0.7.3 只做到「不断引用」，但引用仍挂在会先销毁的对话框上，风险未真正消除。
- **下一步方向及优先级**：R2 取词主线程冻结根治（高）；R3 完成通知（中）。
- **本轮执行结果**：
  - 新增 `promptpop/threads.py`：模块级注册表 `keep_until_finished(th)`——登记线程，`finished` 信号到达（线程已结束）时自动摘除。注册表随进程存活，因此期间**一定**有人持有引用，与父对象生命周期解耦。
  - 应用到三处：`settings_dialog._on_ping`（PingThread）、`overlay._on_fetch_models`（ModelFetcher）、`overlay._run_worker`（OptimizeWorker，防「取消后立刻关窗」场景）。
  - `settings_dialog.closeEvent` 仍断开 `result` 信号（防回调到已销毁的 C++ 对象），但不再依赖对话框自身持有线程。
  - 验证：新增 `tests/test_threads.py`——创建永不结束的 QThread，`del` + `gc.collect()` 后注册表仍持有（不会析构）；`stop()` + `wait()` + 事件循环后自动摘除。通过。
  - 来源：Qt 官方 QThread 文档「删除仍在运行的 QThread 会 qFatal」。
- **遗留问题**：注册表持有期间若线程永不结束（如网络挂死），引用会常驻——已由 worker 的 timeout + cancel 兜底；可接受。

---

## R2 — 取词等待：序列号轮询替代固定 sleep（根治 R7 #9）
- **本轮复盘结论**：R1 完成。`extract_clipboard` 原用 `time.sleep(0.12~0.28)` 最多两次，主线程冻结 0.24~0.56s（浮窗卡住、托盘无响应）。
- **下一步方向及优先级**：R3 完成通知（中）；R4 待调研结果定。
- **本轮执行结果**：
  - `capture._clipboard_seq()`：读 Win32 `GetClipboardSequenceNumber()`。
  - `capture._wait_clipboard_change(prev_seq, timeout, seq_getter, sleeper, poll_interval)`：轮询等序列号变化——**目标程序一写入就返回**（通常远快于 120ms），且等待期间不断 `QApplication.processEvents()`，浮窗/托盘不冻结；8ms 轮询粒度。
  - `extract_clipboard` 改为：清空剪贴板 → 记基线序列号 → Ctrl+Insert → 等变化 → 读；空则 Ctrl+C → 等变化 → 读。`pick_clipboard_delay` 现作为**超时上限**而非固定等待。
  - 验证：`test_ui_smoke` 新增 `test_wait_clipboard_change`——注入 seq_getter/sleeper，断言①第 3 次轮询命中即返回（不多余轮询）②轮询粒度 8ms ③序列号不变时按超时上限有界退出。通过。
  - 来源：Win32 `GetClipboardSequenceNumber` 文档 + Qt 主线程非阻塞等待实践。
- **遗留问题（待真机确认）**：仍有 8ms 级轮询 + processEvents，属「可接受的短暂让出」而非完全零阻塞；真实体验提升幅度需真机划词验证（Chrome/微信等 UIA 失败程序）。

---

## R3 — 库对话框：删除确认 + 模板查重 + 双击加载
- **本轮复盘结论**：R2 完成。自查 `library_dialog.py` 发现两个真实缺陷：**① `_del_template` 删除模板无任何确认**（误触即永久丢失，违反「删前先确认」）；**② `add_template` 盲目 INSERT**，重名会在列表产生难以分辨的重复项。另发现列表不支持双击加载（基础 UX 缺失）。
- **下一步方向及优先级**：R4 完成通知（低）；R5 本地无 key 兜底动作（低）。
- **本轮执行结果**：
  - `ui_util.exec_confirm(parent, title, text, default_yes=False)`：置顶 Yes/No 确认框（替代会被置顶浮窗挡住的裸 `QMessageBox.question`），默认按钮为 No（防误触）。
  - `library_dialog._del_template`：删除前弹确认，显示模板名。
  - `history.find_template_by_name(name)`：按名查模板 id；`_save_template` 重名时问是否覆盖（是→删旧建新，否→取消）。
  - `hist_list` / `tpl_list` 均支持**双击加载**（与「加载选中」等价，少一次点击）。
  - `_status_hint()`：库对话框无状态栏，用窗口标题短暂反馈保存成功。
  - 验证：`find_template_by_name` 增/查/不存在/删后查四态断言通过；编译通过。
  - 来源：SOUL.md 边界「删文件之前，先确认」+ 通用 UX（重名查重、双击加载）。
- **遗留问题**：历史记录没有「删除单条」入口（只有保留天数清理），若用户想删某条敏感历史需手动清库——列为后续候选。

---

## R4 — 完成/失败通知（托盘气泡）
- **本轮复盘结论**：R3 完成。用户生成期间常切到别的窗口，完成后无从得知，只能反复切回来看。
- **下一步方向及优先级**：R5 本地无 key 兜底动作（低）。
- **本轮执行结果**：
  - `overlay._notify(title, body)` + `notify_hook`：overlay 不直接依赖托盘（解耦），由 `app.main` 注入 `_notify`（`tray.showMessage`，3s）。无钩子/钩子抛错均静默，不影响主流程。
  - 触发时机：`_on_done` 成功、`_on_failed` 失败——**且仅当窗口未激活时**（正看着窗口就不打扰）；内容含字数与前 60 字预览。
  - `config.notify_on_done`（默认 True）+ 设置页「生成完成后弹托盘通知」勾选。
  - 验证：`test_ui_smoke` 新增 `test_notify_hook`（钩子收到/无钩子静默/钩子抛错被隔离/失败也通知）。通过。
  - 来源：调研报告建议 4（托盘气泡零依赖优先，Windows Toast 作可选升级，暂不引入 winrt/win11toast 重量级依赖）。
- **遗留问题**：未做「点击气泡唤起浮窗」（需 `tray.messageClicked` 连接，评估价值/实现成本后列为后续候选）；Windows 焦点助手/勿扰时段可能静默气泡（系统行为，无法绕过）。

---

## R5 — 本地无 Key 兜底动作（零成本文本整理）
- **本轮复盘结论**：R4 完成。此前没配 API Key 时应用几乎完全不可用（只有设置页），门槛高。
- **下一步方向及优先级**：R6 剪贴板还原前序列号校验（中）；R7 策略变体扩展（中）。
- **本轮执行结果**：
  - 新增 `promptpop/local_actions.py`：7 个纯本地动作——`clean_ws`（清空白）、`to_bullets`、`to_numbered`、`strip_code_fence`（去 ``` 围栏）、`pretty_json`、`dedupe_lines`、`extract_urls`。
  - `overlay._on_local_tools()`：新增「本地整理」按钮 → 对话框（左列表右预览、实时刷新、「应用到结果框」写入并可继续复制/替换）。全程不调 LLM、不联网。
  - 验证：新增 `tests/test_local_actions.py`（每动作边界断言 + 全动作不抛异常 + 未知动作原文返回）。通过。
  - 来源：调研报告建议 7（本地兜底动作，低成本高价值）。
- **遗留问题**：本地动作结果不进历史库（`add_history` 只在 LLM 路径调用）——若要追溯需补，列为候选。

---

## R6 — 测试稳定性修复 + 本地地址绕开系统代理（根因排查）
- **本轮复盘结论**：接手时 `test_cycle4` 在本机离屏环境**确定性挂死**（8s 后 assert `Esc 取消后 worker 应已退出`）。排查（`sys._current_frames` 抓 worker 栈）发现 worker 阻塞在 `sock.recv` 读**响应头**。先怀疑环境 HTTP 代理拦截 127.0.0.1，抓 env 验证 `HTTP_PROXY/HTTPS_PROXY` 均为 `None` → 排除。真因是**测试顺序竞态**：原测试在 `ov.worker.wait()` 之前就 `srv.shutdown()` 关闭了单线程 mock server，若 worker 尚未连上则 recv 永久阻塞；此外发现**真实产品缺陷**：`engine.build_client` / `ping` 对回环地址（Ollama/本地）未禁用环境代理，用户若配了系统代理，本地模型会被代理挡掉。
- **下一步方向及优先级**：R7 历史单条删除（中）；R8 取消即时性（中）。
- **本轮执行结果**：
  - 修复 `tests/test_cycle4.py`：`srv.shutdown()` 移到 `worker.wait()` **之后**（server 保持在线，worker 在下一片即 break 退出）。验证：重跑 `test_cycle4` 0.80s 内退出 + `CYCLE4 TESTS OK`。
  - **产品修复** `engine.build_client` / `ping`：新增 `_is_loopback(url)`，`127.0.0.1/localhost/::1` 强制 `httpx.Client(trust_env=False)` 直连，避免本地请求被环境代理拦截（Ollama 必走直连）。来源：httpx `trust_env` 文档 + 用户环境代理场景。
  - 验证：10 套测试全绿（含重写前的 `diag` 复现 + 修复后全过）。
- **遗留问题**：`consume_stream` 仅在「收到下一片」时检查 `_stop`，若流式端点**中途卡住**（相邻 chunk 间隔 > read 超时）取消仍要等至超时才响应——R8 根治。

---

## R7 — 历史支持单条删除（闭合 R3 遗留缺口）
- **本轮复盘结论**：R6 完成。自查 `library_dialog` 历史 tab 仅有「加载/打标签/导出」，无删除单条入口（R3 已标注）；只能靠按天清理，用户想删敏感历史需手动清库。
- **下一步方向及优先级**：R8 取消即时性（中）；R9 托盘气泡点击唤起（低）。
- **本轮执行结果**：
  - `library_dialog._del_history`：选中行 → `ui_util.exec_confirm` 确认（默认 No 防误触，与模板删除同模式）→ `history.delete_history(hid)` → 刷新。
  - 验证：`tests/test_ui_smoke.py` 新增 `test_history_delete_single`（注入 `exec_confirm=True`，验证只删选中项、保留其余）→ `[ok] 2b`；`test_buttons_are_wired` 自动覆盖新按钮接线。
  - 来源：通用 UX（删前确认）+ SOUL.md 边界「删前先确认」。
- **遗留问题**：删除后未做撤销（确认即不可逆，与模板一致，可接受）。

---

## R8 — 取消即时性：卡住时也立刻中断流式
- **本轮复盘结论**：R7 完成。R6 遗留：`consume_stream` 的 `should_stop()` 只在收到下一片时检查，若 LLM 流式中途卡住，阻塞在 `recv` 上要等到 read 超时（默认 60s）才响应取消。
- **下一步方向及优先级**：R9 托盘气泡点击唤起（低）；R10 本地动作进历史（低）。
- **本轮执行结果**：
  - `engine.OptimizeWorker`：记录 `self._stream`；`cancel()` 在置停止位后**主动 `self._stream.close()`**——从主线程关底层 socket，让阻塞的 recv 立即报错退出（异常被 `run()` 的 except 捕获 → `cancelled.emit()`）。`finally` 中 `self._stream=None` 防重复关闭。
  - 验证：`tests/test_threads.py` 新增用例——注入假 `_stream.close` 标志，`worker.cancel()` 后断言 `_stop=True` 且 `close()` 被调用 → `[ok] R8`。
  - 来源：httpx/OpenAI 流式中断实践（跨线程关 socket 打断 recv）。
- **遗留问题**：`cancel()` 在 worker 尚未 `create()` 出 stream 的极早期调用时，无 stream 可关，仍靠 `_stop` 标志在首片 break——已覆盖绝大多数场景。

---

## R9 — 托盘气泡点击唤起浮窗（闭合 R4 遗留缺口）
- **本轮复盘结论**：R8 完成。R4 留下「点击气泡唤起浮窗」未做（需 `tray.messageClicked` 连接，评估后实现成本低、价值高）。
- **下一步方向及优先级**：R10 本地动作进历史（低）。
- **本轮执行结果**：
  - `app.py`：把托盘构建抽成 `_build_tray()` / `_make_notify()`；`_build_tray` 内 `tray.messageClicked.connect(hotkey_show)`，完成/失败时点击气泡即唤起浮窗。
  - 验证：`tests/test_ui_smoke.py` 新增 `test_tray_bubble_click_raises_overlay`（离屏无系统托盘 → 强制 `isSystemTrayAvailable=True`，断言 `messageClicked` 已连接且 `emit()` 触发唤起）→ `[ok] 19b`。
  - 来源：Qt `QSystemTrayIcon.messageClicked` 文档。
- **遗留问题**：Windows 焦点助手/勿扰时段可能静默气泡（系统行为，无法绕过）；离屏无法真机验证气泡显示，已标注。

---

## R10 — 本地整理结果可存为历史（闭合 R5 遗留缺口）
- **本轮复盘结论**：R9 完成。R5 留下「本地动作结果不进历史库」——用户用「本地整理」（无 Key 也能用）处理后的文本无法追溯。
- **下一步方向及优先级**：10 轮目标已达成，无新的高优先级可执行方向。
- **本轮执行结果**：
  - `overlay._on_local_tools` 对话框新增「存为历史」按钮：写 `history.add_history("local","local",动作名,原文,结果)`，与其它历史同库、同搜索/标签/导出。
  - 验证：`tests/test_ui_smoke.py` 新增 `test_local_action_save_to_history`（拦截 `_open_modal` 不 exec，找到按钮并点击 → 断言历史含 `mode=local` 且含原文）→ `[ok] 20`。
  - 来源：R5 自评缺口 + 用户「没配 Key 也想用」场景。
- **遗留问题**：无。

---

## 本轮 10 轮汇总（v0.7.4）
- **R1–R5**（前序）：QThread 注册表 / 取词非阻塞轮询 / 库对话框确认查重双击 / 完成通知 / 本地兜底动作。
- **R6**：test_cycle4 竞态修复 + 回环地址绕代理（产品缺陷修复）。
- **R7**：历史单条删除。
- **R8**：取消即时中断流式。
- **R9**：托盘气泡点击唤起浮窗。
- **R10**：本地整理结果存历史。
- **验收**：10 套测试（smoke/rounds/threads/local_actions/ui_smoke/cycle2–6）全绿；新增/改写 4 个测试、2 个产品修复、3 个 UX 缺口闭合。
- **待真机确认**：取词覆盖率（UIA/剪贴板兜底）、气泡在真实系统的显示/点击、Ollama 在系统代理下的直连（代码已处理，需真机验证）。
- **版本**：`version_info.py` 已升 `0.7.4.0`；产物 = 冻结 exe（沿用 `PromptPop.spec` / `PromptPop-onefile.spec` 打包，待构建）。


