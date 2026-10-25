# PromptPop 优化迭代日志 · 第六轮 30 轮循环（v0.7.9）

> 执行：zcode，2026-10-25。承接第五轮（v0.7.8）。本轮扩量为 30 轮，分配：
> R1–R2 API/配置层防御、R3–R11 对抗性测试建设（adv_*，AGENTS.md 对抗性验证要求）、
> R9/R12–R19 修复对抗揪出的问题 + 真缺口、R20–R23 providers 防御与主题一致性、
> R25–R29 收口走查、R30 冻结。
> 回归基线：v0.7.8 全量 24 文件 24 OK。终态：31 文件 31 OK 零失败。

---

## R1 — 配置坏值统一防御（safe_int/safe_float）

- **攻击坐实**（对抗先行）：配置文件被手改成坏值（AGENTS.md 明列的「并发与状态」场景）——
  `pick_clipboard_delay({'clipboard_delay_default': 'abc'})` → ValueError（取词主路径崩）；
  温度 "fast" → float 链崩（优化主路径崩）。共清点 14 处裸 int()/float() 转换点。
- **做了什么**：`util.safe_int/safe_float` + 全部转换点替换（capture×2、app×1、overlay×11）。
- **顺带修复真 bug**：原 `float(x or 0.3)` 写法把用户合法设置的 **0 温度**（greedy 解码）
  因 0.0 为 falsy 悄悄变成 0.3——safe_float 语义修复。
- **验证**：adv_config.py 坏值矩阵（11 组 int + 9 组 float + 0 温度回归）。

## R2 — API 层防御三连

- `_context_block` 非 dict（list/tuple 误传）→ 空串，不再 AttributeError；
- `engine._esafe`：`__str__` 自己抛异常的第三方错误对象不再炸 worker 线程（此前在
  except 块内二次抛出直接杀死线程）；classify_error 全路径字符串化防御；
- `build_timeout` 负值/0（safe_float 不拦负数）夹取到 ≥1s（httpx 负超时语义未定义）。

## R3–R8 — 对抗性测试建设（6 个 adv_* 文件，接入 run_all）

按 AGENTS.md「攻击用例固化为可复现的测试脚本（adv_*.py）加入回归」：

| 文件 | 攻击面 |
|---|---|
| adv_config.py | 坏值矩阵、migrate 幂等与 hostile 值、坏 JSON 恢复、context 非 dict、custom_providers 畸形类型 |
| adv_history.py | SQL 注入四种 payload、1MB 文本、emoji/控制字符、标签分隔符注入、100 同名模板轰炸、坏类型 hid、非 dict 导入条目 |
| adv_util.py | 嵌套/超长模板变量、极端热键串、负尺寸夹取、1MB 行 diff、脱敏边界、坏用量成本估算 |
| adv_text.py | 四反引号/嵌套/未闭合围栏、CRLF、控制字符、万级行编号、500 层嵌套 JSON、1MB 性能 |
| adv_engine.py | 畸形 URL 回环判定、负超时夹取、str 炸裂异常、usage/choices 抛异常的假流 chunk |
| adv_threads.py | 4+4 线程并发 keep/摘除、重复登记、多摘冗余 |

- **价值实证**：首轮即揪出 **4 个真代码 bug**（见 R9）+ 证明 2 处既有防御有效。

## R9 — 修复对抗测试揪出的 4 个真代码 bug

1. `history.import_templates` 非 dict 条目（字符串）→ AttributeError（坏导入文件直接崩）；
2. **中文单字热键**：`_norm_token`/`parse_combo` 的 `isalnum()` 对中文为真——「Ctrl+加」
   被接受并注册无效组合 → 加 `isascii()` 限制；
3. **Win+Space/Win+Tab 失防**：保留表是混合形态（`<cmd>+l` 键裸、`<cmd>+<printscreen>`
   带尖），validate 产出的 `<cmd>+<space>` 两形态都匹配不上 → 归一化去尖比较，三种输入形态全命中；
4. `estimate_cost` 坏 usage（"x" completion_tokens）→ ValueError → safe_float。

另修正 4 个测试自身的错误（假流 chunk 设计、预期过严、断言自相矛盾、test_import 结构）。

## R10 — 保留表修复二段（归一化比较替换双查）

R9 首版双形态查询仍漏混合形态，改为 `_bare()` 统一去尖后比较，adv_util 11/11 过。

## R11 — adv_* 接入 run_all（现 30 文件）

## R12 — 取词重入防御

`extract_clipboard` 等待循环会 processEvents()，期间鼠标钩子再次触发划词会递归取词
（嵌套 Ctrl+C/剪贴板抖动）。加模块级 `_EXTRACTING` 重入标志。

## R13 — diff 大文本主线程护栏

`util.diff_lines`（difflib）最坏 O(n²) 且在主线程同步算——超 20000 行拦截提示，防 UI 冻死。

## R14 — 清除已存 API Key（功能缺口）

「留空 = 不修改」语义下钥匙串里的 Key **永远无法删除**。设置面板两个 Key 行加「清除」
按钮（确认 → set_key("") → placeholder 提示），失败明确报「无法访问系统钥匙串」。

## R15 — R14 接线测试（2 用例：清除/取消）

## R16 — 导出 Markdown 围栏冲突

内容本身含 ``` 时导出结构被截断 → 自动换用 ~~~~ 波浪线围栏。

## R17 — 自定义端点「编辑选中」（功能缺口）

此前只能删了重加。`_CustomProviderDialog` 支持 initial 预填（已存 Key 显示「留空 = 不修改」）；
改名 = 换 id（删旧增新）；Key 留空保留原 Key。

## R18 — R17 接线测试（预填/更新/Key 保留/无选中 noop）

## R19 — 基本 tab 小屏适配

15+ 行表单在 768p/高 DPI 屏会撑爆对话框 → QScrollArea 包裹。

## R20–R21 — providers 层畸形类型防御（启动即崩级）

**攻击坐实**：`custom_providers` 被手改成 dict/字符串/int → `get_all_providers` AttributeError/
TypeError——该函数在 OverlayWindow 构造路径上，**等于启动即崩**。
`_iter_custom` 安全迭代（非 list→空、非 dict 条目剔除）+ add/remove 同防御；
设置面板 _endpoints_tab/_refresh_custom_list 同步。

## R22 — providers 用例固化进 adv_config

## R23 — 主题一致性（三套观感 → 全局统一）

此前 QSS 只设置在浮窗：设置/库对话框永远系统默认色、工具条永远暗色——亮主题用户
看到三套观感。QSS 上移 `ui_util`（DARK_QSS/LIGHT_QSS 唯一来源）+ `apply_app_theme`
Application 级应用；工具条双套 QSS `set_theme`；设置保存后与**启动时**同步
（R29 走查补上启动同步——否则 light 用户先见暗条）。对象名选择器只命中浮窗，通用
选择器惠及其余对话框。真机观感待确认。

## R25 — clicked(checked) 形参陷阱防御

`btn_fetch_models.clicked.connect(self._on_fetch_models)` 的 checked 参数误入
silent 形参（当前 False 碰巧等价）→ lambda 包一层，checkable 陷阱消除。

## R26–R27 — README 全面同步 + 版本号

功能列表补 8 条、架构表补「支撑」层、测试列表补 13 个新文件、版本 0.7.9.0。

## R28 — 全量回归 #1

31 文件 **31 OK 零失败**（test_ui_smoke 全量内 10.2s 通过）。

## R29 — 全量 diff 走查

复查第六轮全部改动，揪出并修复 R23 引入的「启动时工具条未同步主题」；
py_compile 全过。

---

## 本轮周期收尾汇总（v0.7.9，R1–R30）

| 轮次 | 主题 | 类型 |
|---|---|---|
| R1 | 配置坏值 safe_int/safe_float（14 处）+ 0 温度 bug | 真缺陷 |
| R2 | context 非 dict / str 炸裂异常 / 负超时夹取 | 健壮性 |
| R3–R8 | 6 个 adv_* 对抗测试建设 | 回归体系 |
| R9–R10 | 修复对抗揪出 4 bug（导入崩/中文热键/Win+Space 失防/坏用量） | 真缺陷 |
| R11 | adv 接入 run_all | 回归体系 |
| R12 | 取词重入防御 | 健壮性 |
| R13 | diff 大文本护栏 | 健壮性 |
| R14–R15 | 清除已存 API Key | 功能缺口 |
| R16 | 导出 MD 围栏冲突 | 真缺陷 |
| R17–R18 | 自定义端点编辑 | 功能缺口 |
| R19 | 基本 tab 滚动（小屏） | 体验 |
| R20–R22 | providers 畸形类型（启动即崩）防御 + 固化 | 真缺陷 |
| R23 | 主题一致性（全局 QSS + 工具条双主题 + 启动同步） | 体验/一致性 |
| R25 | clicked(checked) 形参陷阱 | 防御 |
| R26–R27 | README/版本号同步 | 文档 |
| R28–R29 | 全量回归 + diff 走查（修启动主题同步） | 验证 |
| R30 | 冻结 + 落大脑 | 收尾 |

- **版本**：`version_info.py` **0.7.9.0**。
- **回归**：`run_all.py` **31 文件 31 OK 零失败**（新增 adv_*×6 + test_round6_ui + 扩展 3 文件）。
- **待真机确认**（不谎报）：
  1. 全局主题在真机的观感（设置/库/消息框配色，QSS 选择器作用范围）。
  2. 工具条亮色主题显示效果（#opt 红色主按钮对比度）。
  3. v0.7.7/v0.7.8 遗留真机项继续有效（划词覆盖率/管理员窗口/provider 错误分类/导入后不重启/变量填空与编辑对话框的置顶层级）。
- **已知不做**：价目表分时化、历史分页、IAccessible 取词层、迭代版本回退、
  `reset_to_defaults` 接入设置面板（现为测试辅助函数，注释已注明现实）。

## 回滚方式
本轮触碰源码 12 个文件（util/capture/app/engine/meta_prompt/overlay/history/
settings_dialog/providers/hotkey/library_dialog/toolbar）+ ui_util + 4 个测试文件 +
README/version_info，全部恢复到 v0.7.8 内容即可；删除新增的 7 个测试文件
（adv_*×6、test_round6_ui.py）；exe 未重打包，桌面产物未动。
