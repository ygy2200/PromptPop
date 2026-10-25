# PromptPop 修复记录 · v0.7.7（2026-10-25，zcode）

> 全面优化轮：全量代码审查（~5000 行全部精读）→ 5 处真缺陷修复 + meta_prompt 质量优化
> → 新增 4 个回归测试文件（15 用例）→ 全量回归 21 OK + 1 pre-existing。
> 基线：v0.7.6（18 文件 17 OK + 1 pre-existing headless keyring）。

## 修复的真缺陷（按严重度）

### 1. 「打标签」按钮一按即 TypeError（功能完全坏）— library_dialog.py
`_tag_history` 调 `ui_util.get_text(..., text=cur)`，而该函数签名是 `default=`。
实参名写错 → 每次点击都抛 `TypeError: unexpected keyword argument 'text'`，
历史标签功能自引入（cycle6）起完全不可用，且无任何测试覆盖。
**修复**：`text=cur` → `default=cur`；新增 `tests/test_library_tag.py` 固化
（传参必须是 default=、标签真实写库、已有标签回填、取消不改库）。

### 2. 重试退避中取消后仍发一轮真实 API 请求 — engine.py
`OptimizeWorker.run` 的安全重试里 `_stop_event.wait(backoff)` 无论返回什么都 `continue`，
退避中点「取消」后仍会 build_client + create 发出下一轮请求（prompt token 已计费风险）。
**修复**：wait 返回 True（被取消）→ `cancelled.emit(); return`。
新增 `tests/test_engine_cancel.py`：退避中取消 → create 仅 1 次；
对照组（不取消）→ create 2 次（排除「根本没重试」假阳性）。

### 3. 导入坏配置文件会静默毁掉用户配置 — config.py
`import_from` 对顶层非 JSON 对象（如 list）静默 `migrate` 成默认配置——
用户随后任意一次 save 就把原配置整体覆盖。
**修复**：顶层非 dict 抛 `ValueError`（设置面板已有 try/except 弹「导入失败」），
内存 data 不动。新增 `tests/test_config_import_guard.py`。

### 4. 浮窗「存为模板」不做同名查重（与库面板行为不一致）— overlay.py
库面板 `_save_template` 有同名确认（覆盖/取消），浮窗同名按钮盲目 INSERT，
同名模板列表出现重复项——「改 A 漏 B」典型。
**修复**：浮窗走同一语义（find_template_by_name → 确认覆盖 → 删旧插新）。

### 5. meta_prompt 的 context 维度「死功能」— meta_prompt.py + overlay.py
`build_messages/build_followup_messages` 支持受众/语言/排除项等额外上下文，
README 也宣称，但 UI 无任何入口、永远传 None——R3 同类「功能已实现但不可达」。
**修复**：
- 浮窗输入框下新增「附加约束」输入框（setMaxLength(2000) 防呆），
  随优化/迭代请求经 `{"extra": ...}` 交给模型；「清空」一并清空。
- `_apply_context`：自定义模板没写 `{ctx}` 占位符时把约束**追加到尾部**而非静默丢弃；
  无 context 时占位符替换为空串不残留。

## meta_prompt 质量优化
- `DEFAULT_META_USER` 硬性要求补一条「不写空话套话：每一条规则都必须可执行、可验证」
  （LangGPT 框架的通病是为填框架灌水）。
- `build_judge_messages` 输出格式收死为固定五行（结构化/可执行性/约束清晰度/忠实原意各 x/10 + 结论），
  不再受模型自由发挥影响，ScrollableResultDialog 里可读、可对比。

## 本轮引入并当场抓住的坑（重要教训）
**overlay._build 里用 QHBoxLayout 子布局包「附加约束+字数标签」两个控件，
在 offscreen 测试环境下把 test_ui_smoke 从「偶发 0xC0000005」放大为「连跑 12 次全崩」。**
- 排查路径：全量回归失败 → 单独跑时好时坏（3过/6挂/8挂/1过/12挂）→
  对照实验：撤掉改动 8/8 过、恢复 0/8 过 → 二分定位：直挂 root 6/6 过、套子布局 12 挂。
- **触发点是「控件套 QHBoxLayout 子布局」本身**，控件（QLineEdit/placeholder/maxLength）无辜。
- 最终形态：两个控件各自 `root.addWidget` 直挂，代码注释写明该环境约束。
- 教训：offscreen Qt 的偶发崩溃不能归因于「headless 通病」就放过——
  必须做禁用/恢复对照实验拿到统计数据再下结论；本次基线「偶发」实际是同一病根的低频表现。

## 验证
- `run_all.py` 22 文件：21 OK + 1 pre-existing（test_rounds headless keyring，基线即如此）。
- 新增 4 测试文件 15 用例全过；test_ui_smoke 最终形态连跑 8/8 + 全量内 OK。
- 版本号 0.7.7.0；README 补两条功能说明。

## 回滚方式
本轮全部改动限于源码/测试/文档，无注册表、无系统配置：
- 单文件回滚：本轮改动点见上表（每处均为小 diff）；
- 整体回滚：恢复 `D:\workbuddy产出\2026-10-13-12-38-27\PromptPop` 下被改的
  7 个源码文件（library_dialog/engine/config/overlay/meta_prompt + tests/run_all + version_info/README）
  到 v0.7.6 内容；无 exe 重打包，桌面产物未动。
