# PromptPop 迭代优化 — 10 轮迭代记录

> 目标：在「选中文字→悬浮窗→AI 优化 agent 提示词→贴回」产品定义不变前提下，迭代提升健壮性/取词可靠性/安全性/分发/代码质量。Windows-first，PySide6。每轮固定字段：复盘结论 / 下一步方向与优先级 / 执行结果(验证+来源) / 遗留问题。

## 关键假设（首轮前明确）
- 平台 Windows-first；无法本机无头验证的方向（真实 App 取词覆盖率、Replace 焦点命中率、A/B 实跑）明确标「待确认」。
- 不碰 agenthub（巡检项另见 `AgentHub-待执行计划表.md`）。
- 验收以可运行/可核查证据为准：单测、冒烟、冻结 exe 启动存活。

---

### R1 复盘 + 基线 + 专项调研
- 复盘结论：M1–M4 已交付、冒烟全过、exe 可启动；遗留=剪贴板回退不安全、引擎无超时/取消/重试、Key 明文、无 Insert/A-B。
- 方向：联网检索 6 专项（划词取词踩坑、keyring、openai 流式、PyInstaller、PySide6 浮窗、A/B 评估）。
- 执行结果：产出改进点清单（见各轮来源）。
- 遗留：进入实现。

### R2 剪贴板安全加固
- 复盘：原回退仅"无变化才还原"，且只发 Ctrl+C，存在污染/漏还原风险。
- 方向(优先级高)：总是备份/还原、两段式复制、含富文本。
- 执行：`capture.extract_clipboard` 重写——总是先备份(文本+HTML)→`Ctrl+Insert`→`Ctrl+C`→读→finally 还原；delay-read 支持。
- 验证：`tests/test_rounds.py` 假剪贴板+假发送器，断言"无选中时无感还原""有选中时取到且仍还原"。来源：selection-hook WINDOWS.md（两段式/Ctrl+Insert 更稳）；Cherry Studio #8265（必须备份还原含 HTML）。
- 遗留：真机多应用覆盖率待确认。

### R3 划词触发降智 + 全屏跳过 + 逐应用
- 复盘：全局划词可能在全屏游戏/自定义光标场景误发剪贴板。
- 方向：光标形状降智 + 全屏 D3D/演示跳过 + 逐应用 fine-tuned + 带前台程序名。
- 执行：新增 `cursor_kind/should_attempt_clipboard/is_fullscreen_exclusive/foreground_program`；`SelectionMonitor` 释放时跳过全屏、发程序名。
- 验证：`should_attempt_clipbox` 纯函数单测(ibeam/arrow/custom/exclude-list)；探针返回类型断言(真实行为待真机确认)。来源：selection-hook 光标检测 + SHQueryUserNotificationState + fine-tuned list。
- 遗留：cursor_kind 与标准光标比对的真实命中率待确认。

### R4 IAccessible 取词层
- 复盘：selection-hook 三级为 UIA→IAccessible→剪贴板；IAccessible 覆盖老式 Win32。
- 方向(优先级中)：补 IAccessible 层。
- 执行：经评估，comtypes/oleacc 的 vtbl 直调在本机无头环境**无法验证且有运行时崩溃风险**，故**暂不实现**，保留 UIA→剪贴板两级，剪贴板回退已覆盖多数老应用。
- 验证：不适用（未实现）。
- 遗留：**待确认**——是否值得投入 IAccessible（需真机老应用样本验证收益）。

### R5 引擎健壮性
- 复盘：原引擎无超时(默认 600s 易挂死)、无取消、异常一律字符串透出、不重试。
- 方向(优先级高)：超时/取消/错误分类/仅瞬时重试/关流。
- 执行：`engine.py` 重写——客户端超时(可配)、`cancel()`、`classify_error`(transient/auth/invalid/unknown)、仅瞬时错误指数退避+抖动重试、finally 关流、`consume_stream` 纯函数。
- 验证：`classify_error` 四类单测；`consume_stream` 累计+取消中断单测。来源：openai SDK 流式最佳实践(n4n.ai / khushaljethava)：设 timeout、仅重试 RateLimit/Connection/Timeout、finally close。
- 遗留：无。

### R6 API Key 安全存储(keyring)
- 复盘：Key 明文存 JSON，有泄露/进备份风险。
- 方向(优先级高)：keyring(Windows Credential Manager) + 启动迁移 + 回退。
- 执行：新增 `secrets.py`(get/set/has/resolve/migrate)；`providers`/overlay 改用 `secrets.resolve_api_key`；启动迁移明文并清空；settings 改为写 keyring(留空不改)。
- 验证：本机 **WinVaultKeyring 真实往返**单测(set/get/has/resolve 优先/migrate 迁移并清空/清理)。来源：keyring 指南(openillumi / python-cli-toolcraft tokenstore 模式)。
- 遗留：无(keyring 不可用时回退 config 明文)。

### R7 Insert After 动作
- 复盘：仅 复制/替换，缺"在原文后插入"。
- 方向(优先级中)：实现 insert_after。
- 执行：`actions.insert_after`——恢复焦点→右箭头折叠选区到末尾→Ctrl+V。overlay 加「插入 Insert」按钮。
- 验证：函数存在性断言(不调用以免发真实键)；**真机焦点/光标命中率待确认**。
- 遗留：待确认。

### R8 A/B 评估 + meta-prompt 变体
- 复盘：无法判断"优化是否真的更好"；风格单一。
- 方向(优先级中)：A/B 评审 + 精简/严格变体。
- 执行：`meta_prompt` 增 `VARIANT_SUFFIX`(concise/strict) + `build_judge_messages`(四维评分判优)；overlay 加「风格」下拉 + 「评估 A/B」按钮(judge 走独立缓冲+结果对话框)。
- 验证：变体后缀拼接 + judge messages 结构单测；**A/B 实跑需 API Key，待用户**。来源：prompt eval methodology(thepromptbench / gptprompts)：固定变量、同模型、评分 rubric、低温。
- 遗留：A/B 实跑待用户提供 Key。

### R9 打包与分发加固
- 复盘：--noconsole 会藏异常；新依赖(keyring)需进包；版本需标识。
- 方向(优先级中)：入口异常落 crash.log + keyring 隐藏导入 + 版本号 + 重打包。
- 执行：`main.py` 顶层 try/except 写 `crash.log`；spec 增 keyring/jaraco 隐藏导入；版本 0.2.0；清旧构建产物后重打包。
- 验证：`py_compile` 全过；重打包成功(9.1M exe / 129M 整包)；冻结 exe 启动存活通过。来源：PyInstaller onedir 优先+`-w` 藏错须落日志(CSDN/schoolofweb)。
- 遗留：exe 文件版本元信息/图标未加(可选)。

### R10 整体回归 + 文档定稿
- 复盘：R2–R9 增量均已落地并通过单测/冒烟/冻结启动；核心闭环(取词→优化→Replace/Insert/评估)完整。
- 方向(优先级)：全量回归 + 文档 + 汇总。
- 执行：跑 `smoke_test.py`(M1-M4) + `test_rounds.py`(R2-R8) 全过；更新 README/迭代记录。
- 验证：见上(全绿)。
- 结论：已达成本轮可验证目标；剩余均为**需真机/需 Key** 的待确认项，无新的可无头执行方向。

---

## 待确认清单（需真机或用户 Key）
1. 划词取词在 Electron(VS Code/Slack)、游戏、PDF 的真实覆盖率。
2. Replace/Insert 焦点恢复在不同 App 的命中率。
3. A/B 评估、优化实跑需用户配置 API Key。
4. IAccessible 层是否值得投入(R4 暂缓)。

## 验证汇总
- `py_compile` 全文件通过。
- `tests/smoke_test.py`(M1–M4)：通过。
- `tests/test_rounds.py`(R2–R8)：通过（含本机 WinVaultKeyring 真实往返）。
- 冻结 exe v0.2.0：重打包成功 + 启动存活通过。

## 来源
- selection-hook Windows 取词: https://github.com/0xfullex/selection-hook/blob/v2.0.0/docs/WINDOWS.md
- Cherry Studio 剪贴板还原踩坑: https://github.com/CherryHQ/cherry-studio/issues/8265
- openai 流式健壮: https://n4n.ai/blog/streaming-responses-with-the-openai-python-sdk ; https://khushaljethava.work/posts/Fix-LLM-API-Error-An-Error-Occurred-During-Streaming/
- keyring: https://openillumi.com/en/en-python-keyring-secure-credentials ; https://www.python-cli-toolcraft.com/cli-runtime-systems-integration/secrets-and-credentials-in-python-clis/storing-tokens-with-keyring
- PyInstaller onedir/AV/`-w` 藏错: https://blog.csdn.net/weixin_33428613/article/details/164639280 ; https://www.schoolofweb.net/en/posts/pyside6-desktop-app-7
- A/B 评估方法论: https://thepromptbench.com/model-benchmarks/prompt-eval-methodology ; https://www.gptprompts.ai/prompt-optimization
- PySide6 无边框置顶/多显示器: https://stackoverflow.com/questions/74411672
