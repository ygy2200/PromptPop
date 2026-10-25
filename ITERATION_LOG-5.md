# PromptPop 迭代记录 · 第五轮 10 轮（v0.5.0 → v0.6.0）

> 承接前四轮（ITERATION_LOG.md / -2 / -3 / -4）。本轮先经网络/GitHub 调研现有实现、最佳实践、流式 API 缺陷与踩坑，再按 复盘→方向→执行→回归 推进。聚焦**无头可验证**的增量；真机/Key 项标「待确认」。每轮固定字段：复盘结论 / 方向 / 执行(验证+来源) / 遗留。不碰 agenthub。

## 首轮前关键假设（已向用户明确）
- 真机取词/Replace 焦点/A-B 实跑/真实代理转发 仍属「待确认」，本轮只实现+单测，不实跑。
- 优先无头可验证增量；不引入重架构变更（保持 PySide6 + OpenAI 兼容协议）。
- 版本推进到 v0.6.0，仍走全新 dist_v6 打包规避安全守卫。
- 失败重试/流式语义严格遵循「仅连接阶段安全重试」结论。

---

### R1 复盘 + 调研
- 复盘：v0.5.0 已覆盖代理/错误指引/配置迁移/调试日志/历史治理/Esc/缩放；五套测试全绿、冻结 exe 启动存活、版本元信息正确。剩余多为真机/Key 待确认项。
- 调研（网络/GitHub，2026-10-13）：
  - **httpx 超时**：业界共识——单 total 超时对 LLM 流式有害，必须拆分 connect/read；默认 600s 太久；read 应远大于 connect（流式两包间隔可长达十几秒）；read 是「两次读取间不活动超时」，正合适。来源：n4n.ai timeout-tuning、力达云 access-timeout/access-proxy。
  - **流式重试非幂等**：超时后无脑重试会让模型把同一问题重生成一遍（重复计费）；仅当「尚未收到任何 token 的连接阶段」失败才安全重试，中段失败应保留已生成内容而非重生成。来源：力达云 access-proxy、bettertoken.ai retry 指南。
  - **全局热键**：pynput 原生 `GlobalHotKeys` 无冲突检测；Windows 原生 `RegisterHotKey` 返回失败可探测冲突；QShortcut 仅前台生效。结论：保留 pynput，增加热键**格式校验**与可读显示，冲突检测列为待确认（需 Win32 接入）。来源：CSDN pynput 冲突检测、PySide6 QShortcut/eventFilter 文档。
  - **剪贴板回退仍是正确路线**：lobehub Windows 桌面自动化明确——CEF/Electron 编辑器 SetValue 失败，必须用剪贴板粘贴；UIA 树在交互后会消失需重 dump。印证 PromptPop 的 UIA→剪贴板回退 + 备份还原策略正确。来源：lobehub windows-desktop-automation。
- 方向：锁定本轮可落地的 8 个增量（见各轮），真机相关继续标待确认。

### R2 httpx 超时拆分（connect/read）
- 复盘：原 `timeout` 单 float（默认 60s）被同时用于连接与读取，流式长生成易被误杀或挂死。
- 方向(高优先)：拆 connect/read；新增 `connect_timeout` 默认 10s。
- 执行：`engine.build_timeout(connect, read)` 返回 `httpx.Timeout(connect, read, write=min(connect,10), pool=5)`；`build_client`/`list_models`/`OptimizeWorker` 透传 `connect_timeout`；配置加 `connect_timeout=10.0`，`request_timeout` 改注释为「读取超时」。
- 验证：`test_cycle5` R2：build_timeout connect/read 值正确；build_client 含/不含代理均返回带 chat 的 client。来源：n4n.ai、力达云。
- 遗留：无。

### R3 安全重试（仅连接阶段）
- 复盘：原重试对 transient 错误一律重试，忽略「流式已生成一半再重试会重复计费」。
- 方向(高优先)：track `received_any`（用 `on_token` 回调 `nonlocal` 实时标记，因流迭代抛异常时 consume_stream 不返回）；仅当 `kind=="transient" and not received_any and attempt<max_retries` 才重试；中段失败给出「生成中断（已保留部分内容，未自动重试）」提示。
- 执行：`consume_stream` 返回 `(full, received)`；worker `run` 内 `_on_tok` 置 `received_any`；按上述条件分流。
- 验证：`test_cycle5` R3：①中段失败→failed 含「生成中断」、不重试；②连接阶段失败→重试→成功；③鉴权错误→不重试。来源：力达云 access-proxy（流式非幂等）。
- 遗留：无。

### R4 热键可自定义 + 校验/显示
- 复盘：热键写死 `<ctrl>+<shift>+space`，用户无法改；状态栏显示原始字符串不友好。
- 方向：设置里可编辑热键；`validate_hotkey` 规范化为 pynput 格式并拦截非法；`format_hotkey` 转可读。
- 执行：`util.validate_hotkey/format_hotkey`；settings 加「热键唤起」行并在保存时校验；app 启动前归一化（非法回退默认）；overlay 状态栏用 `format_hotkey`。
- 验证：`test_cycle5` R4：`Ctrl+Shift+Space→<ctrl>+<shift>+<space>`、`ctrl+alt+k→<ctrl>+<alt>+k`、单键/非法→None、`format` 反向正确。来源：pynput 热键格式约定。
- 遗留：**全局热键冲突检测**（Win32 RegisterHotKey）真机待确认，本轮未接。

### R5 配置导入/导出 + 自动备份
- 复盘：配置只散落 config.json，迁移/重装易丢；保存无备份，写坏即丢失。
- 方向：新增 `export_to/import_from`（经 migrate 安全合并）；`save()` 前先把上一份存为 `.json.bak`。
- 执行：`Config.export_to(path)`/`import_from(path)`；`save()` 写前 `replace` 为 `.bak`。
- 验证：`test_cycle5` R5：导出→导入 round-trip（provider 保留、version 置位、未知键剔除）；首次无 .bak，二次保存生成 .bak。
- 遗留：无。

### R6 多屏/超大窗口夹取
- 复盘：原 `clamp_position` 在窗口大于屏幕时会出现负值/溢出。
- 方向：窗口宽/高 ≥ 可用区时居中，避免溢出。
- 执行：`clamp_position` 对 w/h 超界时 `left + max(margin, (aw-w)//2)` 居中。
- 验证：`test_cycle5` R6：5000×5000 窗口→(8,8) 居中；正常窗口→正确夹取。
- 遗留：真机多屏 `QScreen` 选择（overlay 已用 `screenAt`）待确认。

### R7 历史导出 Markdown
- 复盘：历史仅 JSON 导出，分享/存档不便。
- 方向：新增 `history.export_markdown(rows)` 纯函数。
- 执行：`export_markdown` 按时间/模式/提供商/模型排版，输入/输出包代码块。
- 验证：`test_cycle5` R7：输出以 `# PromptPop 历史导出` 开头且含输入/输出文本。
- 遗留：库对话框内「导出 Markdown」按钮接入真机待确认。

### R8 token 成本估算
- 复盘：完成态只显示 token 数，不直观。
- 方向：按模型价目表估算 USD，完成状态追加 `≈$x.xxxx`（未知模型不显示）。
- 执行：`util.estimate_cost(model, usage, prices=PRICE_TABLE)`（内置 DeepSeek/GPT/Claude 常用价）；overlay `_on_done` 在有用量时计算并追加。
- 验证：`test_cycle5` R8：deepseek-chat 1M+1M → 0.27+1.10；未知模型/空用量→None。来源：各厂商公开价目（2026-10 口径，随厂商调整）。
- 遗留：价目随厂商变动，需用户关注更新（注释已注明）。

### R9 测试覆盖 + 迁移稳健（回归加固）
- 复盘：新增模块函数缺单测；`consume_stream` 返回签名变更需同步旧测试。
- 方向：补 `test_cycle5`（R2–R8 全量）；`test_rounds` 跟随解包 `consume_stream` 新元组；确认 `migrate` 补 `connect_timeout` 默认。
- 执行：新增 `tests/test_cycle5.py`（10 项断言）；修正 `test_rounds` 两处解包；补 `test_cycle5` R9 断言 migrate 含 connect_timeout。
- 验证：`test_cycle5` R9：migrate 后 `connect_timeout==10.0`。
- 遗留：无。

### R10 打包 v0.6.0 + 全量回归 + 文档
- 复盘：R2–R9 落地；需冻结新 exe 并出文档。
- 方向：`version_info`/`__init__` 升 0.6.0.0/0.6.0；全新 `dist_v6` 打包；启动存活 + 版本元信息校验；更新 README/记忆/本记录。
- 执行：升版本；`pyinstaller --distpath dist_v6 --workpath build_v6`；冻结 exe 离屏启动存活、PowerShell 读 FileVersionInfo=0.6.0.0；写本记录；README 升 v0.6.0、补新功能/打包命令/test_cycle5。
- 验证：六套测试全过；冻结 v0.6.0 启动存活 + 版本元信息正确。
- 结论：本轮可验证目标达成；无新可无头执行方向（剩余均为真机/Key 待确认）。

---

## 待确认（需真机/Key）
1. 全局热键冲突检测（Win32 RegisterHotKey 接入）。
2. 真实 HTTP 代理转发、真实 LLM 优化/A-B 实跑（mock 已覆盖链路）。
3. 真机取词覆盖率（Electron/游戏/PDF）、Replace/Insert 焦点命中率、多屏定位。
4. 成本估算价目随厂商变动，需更新 PRICE_TABLE。

## 验证汇总
- `py_compile` 全文件通过。
- 六套测试全过：smoke(M1-M4) / test_rounds(轮1) / test_cycle2(轮2) / test_cycle3(轮3) / test_cycle4(轮4) / test_cycle5(轮5：超时拆分/安全重试/热键/配置导入导出/夹取/历史MD/成本/迁移)。
- 冻结 exe v0.6.0：重打包成功 + 离屏启动存活 + 版本元信息 0.6.0.0 正确。

## 来源
- httpx 超时拆分：n4n.ai「timeout-tuning-for-llm-api-requests」；力达云「access-timeout」「access-proxy」
- 流式非幂等/安全重试：力达云「access-proxy」；bettertoken.ai「api-timeout-troubleshooting-safe-retry-guide」
- 全局热键：CSDN「PySide6 集成 pynput + 冲突检测」；PySide6 QShortcut/EventFilter 文档
- 剪贴板回退正确性：lobehub「windows-desktop-automation」（CEF/Electron 须走剪贴板）
- 成本价目：DeepSeek / OpenAI / Anthropic 官方定价页（2026-10 口径）
