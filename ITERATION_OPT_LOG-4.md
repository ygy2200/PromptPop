# PromptPop 体验优化迭代日志 · 第四轮 10 轮循环（v0.7.6）

> 目标：延续前三轮，继续「找问题→改→验证」；本轮周期额外强调「通过网络/GitHub 广泛调研同类工具与最佳实践」
> （PopClip / Raycast / selection-hook / fshot 等），对照 PromptPop 现状找差距。
> 承接：v0.7.5 收尾 + 一次用户报告的「选不了具体模型」热修（切换 provider 自动拉取，已加 test_overlay_models 9/9）。
> 验收：离屏 UI 冒烟 + 纯函数单测 + 真机项标注「待确认」。
> 假设：只改 `PromptPop/` 源码与测试；不引入重量级新依赖；真机项不谎报。
> 版本：本轮周期统一升到 v0.7.6.x（R1 起 0.7.6.0）。

---

## R1 — 取词光标降智接入主路径（修复非文本拖拽误弹工具条）

- **本轮复盘结论**：第三轮（v0.7.5）已收尾，遗留三项「待真机确认」均离屏不可验证，转可离线验证方向。
  调研 selection-hook / PopClip 等同类工具，对照 PromptPop 现状发现明确缺陷：
  `capture.should_attempt_clipboard`（光标降智纯函数）是**死代码**——`extract_selected_text`
  在 UIA 失败后**无差别**走剪贴板回退（Ctrl+C），导致非文本拖拽（拖图片 / 窗口 / 表格非文本选区）
  也会触发剪贴板回退并弹出工具条；而 PopClip 评测反复强调「误触发/intrusion」是这类工具最大痛点。
- **下一步方向及优先级**：R2 补全 IAccessible 取词层（中高，老 Win32 应用覆盖率）/ 工具条体验优化（中）。
- **本轮执行结果**：
  - `should_attempt_clipboard` 收紧语义：只对 `ibeam`/`unknown` 走剪贴板，`arrow`/`hand`/`custom` 跳过
    （与 selection-hook 最佳实践一致）；自定义光标程序（如 Acrobat）在名单内强制走。
  - `extract_selected_text` 接入光标降智：UIA 失败 → 读光标 → 非文本光标直接返回 `none`，不再无差别 Ctrl+C。
  - 验证：新增 `tests/test_capture_sel.py` **6/6**（UIA 命中不走剪贴板、arrow/hand 跳过、
    ibeam/unknown 走、名单内 custom 强制走）；`test_rounds` 光标降智断言已更新并全过。
  - 来源：
    - selection-hook Windows 文档（UIA→IAccessible→剪贴板三级 + 光标形状降智）：
      https://github.com/0xfullex/selection-hook/blob/v2.0.0/docs/WINDOWS.md
    - PopClip 2025 评测（误触发是最大痛点，需精细控制出现条件）：
      https://www.waerfa.com/popclip-review-2025
- **遗留问题**：
  - **待真机确认**：收紧后是否在某些「文本选择但光标被判定为 arrow/hand」的应用漏取
    （如有，加入 `exclude_cursor_detect` 名单即可）。
  - IAccessible 取词层仍缺（三级变两级），老 Win32 应用 UIA 失败直接跳剪贴板 —— R2 候选。
  - 全量 `run_all.py` 两个 pre-existing 环境失败（与本轮无关）：`test_rounds` 的 `keyring` 后端在 headless
    不可用；`test_ui_smoke` 偶发 `0xC0000005`（headless Qt 通病，第一次含本改动的全量跑它通过）。

---

## R2 — 划词后工具条「优化」一键直达（省一步，浮窗自动开始优化）

- **本轮复盘结论**：R1 光标降智接入完成。复查发现 v0.7.x 的 `should_capture_selection` /
  `should_guide_first_run` / `apply_theme` 等其实都已正确接入（连续两次「疑似死代码」假设落空），
  取词误触发治理已较完整；首次引导、`first_run_done`、主题切换也都在跑。转向「划词即时出结果」的体验打磨。
- **下一步方向及优先级**：R3 设置面板体验（分组/导入导出/即时主题，需先审查是否接入）（中）/
  工具条交互进一步打磨（中）/ 取词覆盖 IAccessible 层（低，边际价值有限）。
- **本轮执行结果**：
  - `overlay.quick_optimize(text)`：预填选中文本 → 显示浮窗 → 自动调 `_on_optimize()`，
    省去在浮窗再点一次「优化✨」。
  - `app.toolbar_optimize` 改调 `quick_optimize`（保留 `owner_hwnd`=划词来源窗口 的替换目标记录）。
  - 验证：`test_overlay_models` 新增 `test_quick_optimize_pipeline`（10/10 全过）；
    `test_ui_smoke` 全过（UI SMOKE OK），工具条优化按钮接线未破坏。
  - 来源：PopClip / selection-hook 范式——「选中即操作」，减少中转点击。
- **遗留问题**：
  - 自动优化会立即消耗 API（已配 Key 时）；无 Key 用户会自动提示去设置，符合预期。
  - 仍无 IAccessible 中间层（老 MSAA-only 应用取词靠剪贴板回退），边际价值有限，留待后续。

---

## R3 — 设置面板「备份与迁移」tab（把 config 导入/导出接进 UI）

- **本轮复盘结论**：R2 划词一键优化完成。复查 `config.py` 发现 `import_from` / `export_to`
  早已实现、且经 `config_test`（或既有冒烟）验证可用，但设置面板**没有入口**——
  用户想换电脑/备份配置只能手工翻 JSON。这是「功能已实现但不可达」的体验缺口。
  另：R1/R2 新增 3 个测试文件（`test_capture_sel` / `test_overlay_models` / `test_settings_backup`）
  尚未接入 `run_all.py`，回归覆盖有洞。
- **下一步方向及优先级**：R4 全量回归把 3 新文件纳入 `run_all.py`（已顺手完成，见执行结果）/
  取词「夹取后窗口失焦→替换粘回自身输入框」治理（中，工具条来源窗口归因再收紧）/
  历史面板体验（中）。
- **本轮执行结果**：
  - 设置面板新增第 4 个 tab「备份与迁移」：导出（QFileDialog.getSaveFileName → `config.export_to`）、
    导入（QFileDialog.getOpenFileName → 二次确认 → `config.import_from`），成功/失败均弹提示。
    导入提示里明确告知「为保证 Key/端点生效请重启」。
  - 把 3 个新增测试文件接入 `tests/run_all.py`（FILES 列表），回归覆盖补全。
  - 验证：`tests/test_settings_backup.py` **3/3**（导出调 export_to、导入确认后调 import_from、
    取消不调 import_from）；`run_all.py` 现 14 文件，除 pre-existing 的 `test_rounds` 头less keyring
    失败外全部 OK（capture_sel 6/6、overlay_models 10/10、settings_backup 3/3 已纳入）。
  - 来源：`config.py` 既有 `export_to/import_from`（原子写 + .bak 回滚）已具备；仅补 UI 入口。
- **遗留问题**：
  - 导入后提示「请重启」是诚实告知；但 `import_from` 是否即时刷新内存中各模块引用（如已解析的
    provider 列表）仍依赖重启——**待真机确认**导入后不重启是否还有漏刷处（如浮窗下拉模型列表）。
  - `test_rounds.py` 的 `secrets.backend_available()` 在 headless 环境恒假，属环境限制非回归，
    真机带钥匙串后端即过。

---

## R4 — Replace/Insert 剪贴板还原 + 管理员窗口失败提示（核心动作体验打磨）

- **本轮复盘结论**：R3 设置入口补齐。复查 `actions.py`（Replace/Insert 核心动作）发现两个真实缺口：
  ① 粘贴后**不还原用户原有剪贴板**——用户此前复制的内容被静默覆盖（行业最佳实践
  dictate.app 等明确点名「否则用户的重要复制内容就没了」）；② 自动粘贴失败时只给笼统的
  「未能定位原窗口」，而最常见的真因是**目标窗口以管理员（高完整性）运行**：Windows UIPI
  禁止普通进程向高权限窗口发模拟输入，SetForegroundWindow/Ctrl+V 静默失效，用户完全摸不着头脑。
- **下一步方向及优先级**：R5 历史/模板库面板交互细化（中）/ 本地整理动作扩充（零成本路径，中）/
  首次引导聚焦（低）。优先 R5 找一处真实可验证的缺口。
- **本轮执行结果**：
  - `replace_selection` / `insert_after`：粘贴前备份 `clipboard_get_text()`，成功后才
    `clipboard_set_text(old)` 还原；失败则保留新文本（供手动 Ctrl+V）。
  - 新增 `actions.is_target_elevated(hwnd)`（OpenProcess+OpenProcessToken+TokenElevation）与
    `is_current_elevated()`（IsUserAnAdmin），非 Windows 安全返回 False。
  - `overlay._replace_fail_msg`：目标是管理员且自身不是 → 具体指引「请手动 Ctrl+V 或把本程序也
    以管理员运行」；否则保持原笼统提示。`_on_replace`/`_on_insert` 失败分支改用它（并加 warn 颜色）。
  - 验证：新增 `tests/test_actions_clipboard.py` **7/7**（成功还原/失败保留/insert 还原/
    非 nt 安全返回/`_replace_fail_msg` 两类分支）；该文件刻意不建 QApplication（剪贴板全 mock、
    `_replace_fail_msg` unbound 调用），避开离屏 Qt teardown 崩溃（与 test_ui_smoke 偶发
    0xC0000005 同源），已连跑 3 次 exit=0 稳定；`run_all.py` 现 15 文件，除 pre-existing 的
    `test_rounds` keyring 失败外全 OK。
  - 来源（网络调研，UIPI 限制 + 剪贴板还原最佳实践）：
    - Windows UIPI：普通进程无法向高完整性（管理员）窗口发输入，Ctrl+V/SetForegroundWindow 静默失效：
      https://www.renrendaima.com/wap/article/27066.html
    - dictate.app：剪贴板注入流程「存原→写新→Ctrl+V→延迟还原原剪贴板」：
      https://bizarro.dev.to/howmindswork/how-i-inject-text-into-any-windows-app-including-elevated-processes-4jl6
- **遗留问题**：
  - **待真机确认**：管理员窗口场景的真实表现（提示是否准确、把 PromptPop 以管理员运行是否真能跨 UIPI 粘贴）。
  - `is_target_elevated` 仅检测管理员；企业环境的「完整性级别≠管理员」细粒度场景未覆盖（保守返回 False，不影响可用性）。

---

## R5 — 本地整理动作扩充（零成本路径补常用预清理）

- **本轮复盘结论**：R4 剪贴板还原 + 管理员提示完成。复查 `local_actions.py`（无需 Key、
  不联网的零成本路径）仅 7 个动作；prompt 工程师在发往 LLM 前常做的「中文标点转英文」「删空行」
  「删 URL」缺失，用户只能手写或绕路。
- **下一步方向及优先级**：R6 历史面板批量清空（中）/ 工具条零成本入口（中）/ 取词 IAccessible 层（低）。
- **本轮执行结果**：
  - 新增 3 个纯函数并注册进 `ACTIONS`（库面板的「本地整理」是动态读 `names()/ACTIONS` 渲染，
    无需改 UI 即自动出现）：`to_english_punct`（中文全角标点转 ASCII）、`remove_blank_lines`
    （删所有空行，区别于 clean_ws 保留单空行）、`strip_urls`（删 URL，extract_urls 反操作）。
  - 验证：`test_local_actions.py` 全过（新增 3 组断言：标点转写含引号/括号、删空行、删 URL 且压多余空格）；
    本地整理面板自动出现 3 个新动作。
  - 来源：prompt 工程常见预清理需求（英文 LLM 的标点归一、脱敏去链）。
- **遗留问题**：动作集仍可按需扩充（如 Markdown 表格互转、列表转表格），属增量功能非缺陷，待用户反馈。

---

## R6 — 历史「清空全部」（库面板补批量重置入口）

- **本轮复盘结论**：R5 本地动作扩充。复查 `library_dialog`（历史/模板库）仅支持单条删除/导出，
  无批量「清空全部」——用户想重置历史只能逐条删（尤其已配合 `history_retention_days` 自动清理后，
  想立刻清空更频繁），体验差且慢。
- **下一步方向及优先级**：R7 工具条零成本入口（中）/ 取词覆盖（低）。
- **本轮执行结果**：
  - `history.clear_history()`：不可逆，返回删除条数并重置 `sqlite_sequence`（清空后 id 不接着旧值跳）。
  - 库对话框历史 tab 新增「清空历史」按钮 + `_clear_history`（强确认，空列表时提示无需清空）。
  - 验证：新增 `tests/test_history_clear.py` **3/3**（纯 DB 清空返回条数/空集返回 0/对话框接线
    确认后调用 clear_history 且列表清空）；已接入 `run_all.py`；全量除 pre-existing `test_rounds`
    keyring 失败外全 OK。
- **遗留问题**：清空不入回收站/无二次备份——属设计（不可逆操作已强确认）；真机确认提示是否足够醒目。
  `test_rounds` 的 headless keyring 失败与本轮无关。

---

## R7 — 划词工具条「整理」按钮（零成本入口前置）

- **本轮复盘结论**：R6 历史批量清空完成。复查划词工具条仅「优化提示词 / 复制」两操作；
  没配 Key 的用户想做零成本本地整理，得先开浮窗再点「本地整理」，多一步；而「优化」必走 LLM。
- **下一步方向及优先级**：R8 复查找一处真实可验证缺口（待定）。
- **本轮执行结果**：
  - `SelectionToolbar` 新增 `organize` 信号 + 「整理」按钮（Tooltip 注明无需 Key）。
  - `app.toolbar_organize`：预填选中文本 → 显示浮窗 → 打开 `overlay._on_local_tools()`，
    结果写入结果框；区别于「优化」（需 Key 调 LLM）。`toolbar.organize.connect(toolbar_organize)` 已接。
  - 验证：`test_ui_smoke.py` 新增 `test_toolbar_organize_signal`（点「整理」触发 organize 信号）；
    `run_all.py` 全过（除 pre-existing `test_rounds` keyring）。
  - 来源：PopClip/selection-hook「选中即操作、减少中转点击」范式。
- **遗留问题**：本地整理面板内仍需手动选动作；可考虑「整理」直接套用上次动作（待用户反馈，非缺陷）。

---

## R8 — 网络错误分类改用 openai 异常类型判定（不再依赖易变的报错文案）

- **本轮复盘结论**：R7 工具条整理入口完成。复查 `engine.classify_error` 发现它纯靠
  `str(e).lower()` 匹配 "401"/"api key"/"invalid" 等**文案**来区分 auth / invalid / unknown。
  文案随 SDK 版本与服务商而变（同一错误在不同 provider 下措辞不同），匹配不上就退化成
  `unknown`，而 `unknown` 的提示是「国际接口可能需代理」——**会把「Key 填错」误导成
  「网络/代理问题」**，用户照着去配代理，越调越偏。openai SDK 本身已把这些语义固化成
  异常类（AuthenticationError / PermissionDeniedError / BadRequestError / NotFoundError）。
- **下一步方向及优先级**：R9 输入体验（字数提示，中）/ R10 收尾一致性复查（中）。
- **本轮执行结果**：
  - `classify_error` 在「瞬时错误」判定之后、文案兜底之前，插入一层**异常类型判定**：
    延迟 `from openai import ...`（缺库则静默跳过，保持零硬依赖），
    `AuthenticationError/PermissionDeniedError → auth`、`BadRequestError/NotFoundError → invalid`；
    类型判定失败才回落到原文案匹配（保留对未装 openai 环境的兼容）。
  - 保留 `engine._transient_errors` 的可注入性（`test_rounds` 的 monkeypatch 仍生效）。
  - 验证：新增 `tests/test_engine_errors.py` **6/6**（瞬时类注入、文案兜底分支、
    真实 openai AuthenticationError/BadRequestError 类判定——缺库则跳过该项）；
    已接入 `run_all.py`（现 17 文件）。
  - 来源：openai-python SDK 异常层级（`openai.AuthenticationError` 等为 `APIStatusError` 子类，
    官方即按类型区分 401/400/404），类型判定比字符串匹配稳定。
- **遗留问题**：
  - 仅覆盖 openai SDK；DeepSeek/OpenAI 兼容端点大多复用同一套 SDK 故受益，
    自研 HTTP 客户端路径仍走文案兜底（**待真机确认**各 provider 的实际分类是否准确）。

---

## R9 — 输入框实时字数提示（超限提前标黄/标红，不再「点了才知道超了」）

- **本轮复盘结论**：R8 错误分类加固完成。复查输入链路发现：`max_input_chars`
  （单条输入上限）在 `_on_optimize` / `_on_iterate` / `_on_ab` 三处都会**硬拦截**，
  但用户只有在点完按钮、看到状态栏红字时才知道超了——而此时已经白点一次。
  这类「限制不前置」是典型的体验缺口（PopClip 等工具强调即时反馈）。
- **下一步方向及优先级**：R10 收尾——把字数提示覆盖到同样被拦截的迭代框（中，一致性缺口）。
- **本轮执行结果**：
  - 新增纯函数 `util.format_char_count(n, mx) -> (文本, 类别)`：类别 ∈ error/warn/info，
    warn 取 **90%<占比<100%**（开区间——恰好等于上限时提交仍允许，故按 info 处理，
    与 `_on_optimize` 的 `len(text) > mx` 严格拦截保持一致）。
  - 浮窗在输入框下方加右对齐字数标签，`input_box.textChanged` 实时刷新，
    逼近上限标黄、超限标红。
  - 验证：新增 `tests/test_input_count.py`（纯函数，**不建 QApplication**，
    规避离屏 Qt teardown 崩溃）；已接入 `run_all.py`（现 18 文件）。
- **遗留问题**：
  - 字数提示当时**只覆盖主输入框**，迭代框同样被拦截却无提示 —— R10 修。
  - 按字符数（`len`）而非 token 计费口径估算，与真实 token 数有偏差（够用作防爆单粗筛）。

---

## R10 — 字数提示覆盖迭代框（统一渲染 + quiet 模式）+ 超限给解法（收尾轮）

- **本轮复盘结论**：R9 的实时字数提示只接了主输入框 `input_box`，但同样受
  `max_input_chars` **硬拦截**的还有迭代框 `iter_edit`（`_on_iterate`）——用户填完
  迭代要求、点「迭代 ↻」才被拦，与 R9 要解决的「点了才知道超了」是同一个问题，
  属于典型的**改 A 漏 B**（本项目历史上反复出现：v0.7.1 尺寸记忆、v0.7.2 快捷键、
  v0.7.3 死代码、v0.7.5 默认热键写法，全是这一类）。另：超限提示只说「请精简」
  却不给解法，与 R4「只报问题不给方案」同类。
- **下一步方向及优先级**：本轮为第 10 轮收尾。**已确认无新的高优先级可离线验证缺口**——
  剩余项要么需真机（取词覆盖率/管理员窗口/代理下 Ollama），要么属增量功能非缺陷
  （A/B 阈值可见性、动作集扩充）。故本轮做一致性收口 + 全量回归 + 冻结产物。
- **本轮执行结果**：
  - 抽出 `overlay._render_char_count(label, n, quiet=False)` 统一染色渲染（消除 R9 的
    重复逻辑），颜色表提为类属性 `_COUNT_COLOR`。
  - 迭代行新增 `iter_count` 标签，`iter_edit.textChanged → _update_iter_count`，
    `_build` 末尾初始化。
  - **quiet 模式**：迭代要求通常只有十几个字，常驻「0 字（上限 8000）」是噪音——
    常态（info）留空，仅逼近（warn 黄）/ 超限（error 红）时才冒出；且删回正常后
    **必须清空**（否则残留提示会误导，已写进断言）。
  - `_on_optimize` 超限提示补可操作解法：「可先用『本地整理』压缩空白/删空行，或分段优化」。
  - 验证：`test_input_count.py` 扩展 4 组渲染断言（**unbound 调用 + 假 label，
    不建 QApplication**，规避离屏 teardown 崩溃）全过；`test_ui_smoke.py` 新增
    `test_iter_count_appears_near_limit`（17c：短文本留空 / 95 字标黄 / 150 字标红 /
    删回清空），连跑 2 次 exit=0；全量 `run_all.py` **18 文件 17 OK**，唯一失败
    `test_rounds.py` 为 pre-existing（headless keyring `backend_available()` 恒假，
    环境限制非回归，本轮 10 轮每次全量均如此）。
  - 来源：本项目历史缺陷模式（改 A 漏 B）+ PopClip「即时反馈、限制前置」范式。
- **遗留问题**：
  - A/B 评估的「原文+结果**合计**」阈值仍不可见（点「评估 A/B」才知被拦），
    同理可前置提示——属增量优化，非缺陷。
  - 字数按字符数而非 token（粗筛够用）。
  - 真机确认项见下「本轮周期收尾汇总」。

---

## 本轮周期收尾汇总（v0.7.6，R1–R10）

| 轮次 | 主题 | 类型 |
|---|---|---|
| R1 | 取词光标降智接入主路径（`should_attempt_clipboard` 原为死代码 → 非文本拖拽误弹工具条） | 真缺陷 |
| R2 | 划词后工具条「优化」一键直达（`quick_optimize`） | 体验 |
| R3 | 设置面板「备份与迁移」tab（把已有 `export_to/import_from` 接进 UI）+ 3 新测试接入 `run_all` | 体验/回归补全 |
| R4 | Replace/Insert **剪贴板还原** + 管理员（UIPI）窗口失败专项提示 | 真缺陷 |
| R5 | 本地整理扩充 3 动作（中文标点转英/删空行/删 URL） | 零成本功能 |
| R6 | 历史「清空全部」（`history.clear_history` + 库面板入口） | 功能补齐 |
| R7 | 划词工具条「整理」按钮（无 Key 用户零成本入口前置） | 体验 |
| R8 | 错误分类改用 openai **异常类型**判定（不再依赖易变文案，避免把 Key 错误导成代理问题） | 健壮性 |
| R9 | 输入框实时字数提示（超限提前标黄/标红） | 体验 |
| R10 | 字数提示覆盖迭代框（统一渲染 + quiet 模式）+ 超限给解法 | 一致性收口 |

- **版本**：`version_info.py` 已为 **0.7.6.0**（R1 起）。
- **回归**：`run_all.py` 18 个文件，17 OK + 1 pre-existing（`test_rounds` headless keyring）。
- **待真机确认**（离屏不可验证，不谎报）：
  1. R1 收紧光标降智后，是否有「确实是文本选择但光标被判为 arrow/hand」的应用漏取。
  2. R4 管理员窗口场景提示是否准确、把 PromptPop 以管理员运行能否跨 UIPI 粘贴。
  3. R8 各 provider（DeepSeek/Ollama/自定义端点）的实际错误分类是否落到正确类别。
  4. 导入配置后不重启是否有漏刷处（如浮窗模型下拉）。
