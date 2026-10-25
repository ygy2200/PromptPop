# PromptPop 迭代记录 · 第六轮（v0.6.0 → v0.7.0）

> 循环：复盘 → 方向 → 执行 → 回归，共 10 轮（R1–R10）。
> 约束：不碰 agenthub / 不调 `hub_*`；依赖只在隔离 venv；无法无头验证的方向一律标「待确认」。

---

## R1 · 复盘（起点：v0.6.0，`dist_v6`，六套测试全绿）

**已完成**：超时拆分（connect/read）、安全重试语义、热键可自定义、配置导入导出+自动备份、
超大窗夹取居中、历史导出 Markdown、token 成本估算、test_cycle5。

**未解决 / 风险**：
1. 高 DPI 屏（125%/150%）未显式设置缩放策略 → 界面偏大或模糊（Qt6 默认虽开缩放，但取整策略会吃掉精确比例）。
2. meta-prompt 仍是自建六维度，未跟 2025 主流框架（CRAFT / ICE），且无「受众/排除项」等补充约束注入口。
3. 结果只能整体替换，看不到「原文 vs 优化」差了什么。
4. Key/地址填错时只能靠一次真实优化请求报错，缺低成本预检。
5. 历史只能按文本搜，无标签；模板库不能整体导入/导出（换机迁移要手抄）。
6. 浮窗快捷键硬编码在 `keyPressEvent`，不可单测、无法统一维护。

**遗留待确认（需真机/Key，本轮不实跑）**：真机取词覆盖率、Replace/Insert 焦点命中率、
真实代理转发、真实 LLM 优化/A-B 质量、Win32 全局热键冲突探测。

---

## R2 · 高 DPI 策略（方向优先级：高）

- **依据**：Qt6 默认启用 DPI 缩放，但默认取整策略（Round）在 125%/150% 屏上会把 1.25 取整成 1 或 2，导致界面过大/过小；`PassThrough` 保留精确因子；`AA_UseHighDpiPixmaps` 让图标按设备像素比取 @2x 资源。检索关键词：`PySide6 DPI awareness high DPI scaling setHighDpiScaleFactorRoundingPolicy best practice 2025`。
- **落地**：`app.apply_high_dpi_policy()`（必须在 `QApplication` 实例化前调用），`main()` 首行调用。抽成函数是为了可断言。
- **验收**：`test_cycle6::test_high_dpi_policy` 断言返回策略 == `PassThrough`。
- **结果**：✅ 通过。

## R3 · meta-prompt 升级到 CRAFT + ICE，并支持上下文注入

- **依据**：2025 主流提示工程框架 CRAFT（Capability/Role/Action/Format/Tone）与 ICE（Instruction/Context/Examples），强调显式约束（格式/长度/排除项）、指定受众与语气。检索关键词：`prompt engineering optimization tool meta prompt structure best practices LLM 2025`。
- **落地**：
  - `DEFAULT_META_USER` / `DEFAULT_META_SYSTEM` 重写为 CRAFT 五维 + ICE 补齐维度。
  - `_context_block(context)` 支持**任意键**（已知键用中文友好标签，未知键含中文键原样渲染 `键：值`）。
  - `build_messages` / `build_followup_messages` 新增 `context` 参数，模板尾部 `{ctx}` 占位符替换。
- **本轮自我纠错（真缺陷）**：
  1. `system` 模板漏了 ICE 的「上下文/示例」→ 补上，避免两条模板质量不齐。
  2. `_context_block` 原来只认 `audience/output_format/language/extra` 四个英文键，传中文键或自定义维度会被静默丢弃 → 改为通用渲染。
- **验收**：`test_cycle6::test_meta_prompt_craft_ice`（两模板都含 CRAFT 五维 + ICE）、`test_context_injection`（首轮 + 多轮都注入、无占位符残留）。
- **结果**：✅ 通过。

## R4 · 差异视图（原文 vs 优化结果）

- **落地**：`util.diff_lines(old, new)` 行级统一 diff（`  ` 相同 / `- ` 仅原文 / `+ ` 仅优化，纯函数）；`overlay._on_diff()` 用只读文本框展示并统计 +/- 行数。
- **接线**：Ctrl+D。
- **验收**：`test_cycle6::test_diff_lines`（增/删/相同/全等/全空）。
- **结果**：✅ 通过。

## R5 · 连通性预检 `ping`

- **落地**：`engine.ping(base_url, timeout, proxy)` —— 只判「网络层可达」：`httpx.RequestError`（连接被拒/超时/DNS 失败）才 False；4xx/5xx 说明服务在响应，视为可达，鉴权交给后续 worker 报。
- **接线**：设置页「测试连接」按钮 + `PingThread(QThread)` 异步，避免点一下卡住界面。
- **验收**：`test_cycle6::test_ping_unreachable`（`http://127.0.0.1:1` → False 且不无限等待，实测 2.1s）、`test_ping_empty_url`。
- **结果**：✅ 通过。**真实代理环境下的可达性判定的准确性属「待确认」**（无代理环境验证）。

## R6 · 历史标签

- **落地**：`history` 加 `tags` 列（迁移式 `ALTER TABLE`）；`set_tags(hid, tags)`、`search_by_tag(tag)`；
  `list_history` 返回 8 列；`export_markdown` 输出标签；`util.filter_history` 把标签纳入搜索；
  `library_dialog` 加「打标签」「导出 Markdown」按钮 + 列表显示 `#标签`。
- **本轮自我纠错（真缺陷）**：`search_by_tag` 原 SQL `WHERE tags LIKE '%,tag,%'` 匹配不到**首尾**标签（存储形如 `a,b` 无包裹逗号）→ 改为 `WHERE (',' || COALESCE(tags,'') || ',') LIKE ?`。
- **回归影响**：历史行由 7 列变 8 列 → 同步修 `library_dialog._apply_hist_filter`（改为 `row[:7]` + 可选 `row[7]`，兼容新旧）、`_export_history`（带 tags）、`test_cycle5` 夹具。
- **验收**：`test_cycle6::test_history_tags`（8 列 / 写入 / 首尾命中 / 搜索 / 清空）。
- **结果**：✅ 通过。

## R7 · 模板库导入 / 导出

- **落地**：`history.export_templates()` → 可序列化 dict 列表（能直接 `json.dump`，与 import 往返兼容）；
  `history.import_templates(items, merge=True)` → 同名跳过、异名新增，返回 `(新增, 跳过)`；脏数据（空名/非列表）不崩。
- **接线**：库对话框「导出模板」「导入模板」按钮。
- **验收**：`test_cycle6::test_template_import_export`（去重 / 空列表 / 空名不入库）。
- **结果**：✅ 通过。

## R8 · 浮窗快捷键统一解析

- **落地**：`util.resolve_overlay_shortcut(ctrl, shift, key_name)` 纯函数；`overlay.keyPressEvent` 改为查表派发：
  `Ctrl+Enter` 优化 / `Ctrl+D` 差异 / `Ctrl+I` 插入 / `Ctrl+R` 替换 / `Ctrl+Shift+C` 复制 / `Esc` 取消并隐藏。
- **验收**：`test_cycle6::test_overlay_shortcuts`，含**不误触发**断言（无修饰键单字母不触发、未定义组合返回空）。
- **结果**：✅ 通过。

## R9 · 测试与回归

- 新增 `tests/test_cycle6.py`（R2–R8 全量 + 不误触发断言）。
- 修 `tests/test_cycle5.py`：历史行夹具补第 8 列 `tags`（R6 改列结构引入的回归）。
- **全套回归**：`smoke_test` / `test_rounds` / `test_cycle2` / `test_cycle3` / `test_cycle4` / `test_cycle5` / `test_cycle6` —— **七套全绿**。
- 本轮测试侧自身返工（非产品缺陷）：PySide6 枚举不能 `int()` 比较；`filter_history` 断言用了打标签前的旧快照；误把 `export_templates` 的 dict 当行对象——三处均为测试构造错误，已修正。

## R10 · 版本与打包

- `__init__.py` → `0.7.0`；`version_info.py` → `0.7.0.0`。
- 新增 `PromptPop-onefile.spec`：**单文件**打包（`EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas)`，无 `COLLECT`），
  产物直接输出到桌面 → `C:\Users\y\Desktop\PromptPop.exe`。
- 同时保留 `PromptPop.spec` one-folder 产物 `dist_v7/PromptPop/PromptPop.exe`（启动更快，适合固定目录长期用）。
- **取舍说明**：onefile 每次冷启动需把依赖解压到临时目录（约 3–8 秒），换来「就一个 exe，可直接放桌面/拷走」；
  one-folder 启动快但必须整目录携带。
- 验证：冻结 exe 离屏启动存活 + PowerShell `FileVersionInfo` 版本元信息核验。

---

## 本轮结论

| 项 | 结果 |
|---|---|
| 改动文件 | `promptpop/{app,meta_prompt,util,engine,history,library_dialog,settings_dialog,overlay}.py` |
| 新增文件 | `tests/test_cycle6.py`、`PromptPop-onefile.spec`、`ITERATION_LOG-6.md` |
| 回归文件 | `tests/test_cycle5.py`（历史 8 列夹具） |
| 测试 | 七套全绿 |
| 交付 | 桌面单文件 `PromptPop.exe`（v0.7.0）+ `dist_v7/` one-folder 备份 |

## 遗留（待确认，需真机 / API Key，本轮未实跑）

1. 真机取词覆盖率：Electron 应用（VS Code/Slack）、游戏、PDF 阅读器。
2. Replace / Insert 的焦点命中率（依赖前台窗口恢复，无头无法验）。
3. 真实 HTTP 代理下的连通性预检判定准确性（mock 已覆盖不可达分支）。
4. 真实 LLM 下的优化质量与 A/B 评审效果、CRAFT/ICE 模板实际收益（需 Key 实跑对比）。
5. 多屏 + 高 DPI 实机观感（125%/150% 缩放下的浮窗清晰度）。
6. 全局热键冲突检测（纯 pynput 无原生探测，需接 Win32 `RegisterHotKey`）。
7. `util.PRICE_TABLE` 价目随厂商变动，需定期更新。
