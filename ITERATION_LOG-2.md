# PromptPop 迭代记录 · 第二轮 10 轮（v0.2.0 → v0.3.0）

> 承接第一轮（见 ITERATION_LOG.md）。目标不变，重点补**可验证性**与**健壮性/UX**。每轮固定字段：复盘结论 / 下一步方向与优先级 / 执行结果(验证+来源) / 遗留问题。无头不可验证项标「待确认」。不碰 agenthub。

## 关键假设（首轮前）
- 最大缺口：v0.2.0 的优化链路没有 API Key 就无法验证 → 本轮核心引入**本地 mock LLM server 做端到端测试**。
- 优先无头可验证增量；真实硬件/真实 Key 项标待确认。

---

### R1 复盘 + 调研
- 复盘：v0.2.0 功能完整、单测/冒烟/冻结启动均过；但优化链路无 Key 不可验；结果可能带 ``` 围栏；无 Ollama 探活；无单实例；无历史搜索。
- 方向：检索 mock server 测试法、LLM 输出清洗、Ollama 探活、单实例。
- 执行：确定用 http.server 起 OpenAI 兼容 SSE mock（OpenAI 官方测试亦用 mock server 模式）。
- 遗留：进入实现。

### R2 mock LLM server + 端到端测试 ★本轮核心
- 复盘：无法无 Key 验证「取词→优化→后处理→入库」全链路。
- 方向(最高优先)：本地 mock + 两层 e2e。
- 执行：`tests/mock_llm.py`（OpenAI 兼容 /v1/chat/completions SSE + /api/tags 探活）；`tests/test_cycle2.py`：① OptimizeWorker 直连 mock（真实 SDK 流式路径）② Overlay 全流程——config 指向 ollama+mock base_url，`_on_optimize`→事件循环→断言结果区更新+去围栏+入库。
- 验证：`test_cycle2.py` 全过（含 Overlay 全流程无 Key）。来源：openai-python 测试用 mock server；respx/pytest-mock 备选。
- 遗留：无（关键缺口已闭合）。

### R3 输出后处理
- 复盘：模型可能把提示词包进 ``` 围栏或加 "Sure, here's" 前缀，直接粘贴给 agent 不干净。
- 方向：去围栏/赘述前缀。
- 执行：`postprocess.py`（strip_fences 支持 ``` / ~~~ / 悬空开围栏；strip_leading_prefixes 仅去英文客套；postprocess_output 组合）；overlay `_on_done` 对最终结果清洗后再显示+入库。
- 验证：单测（围栏/悬空/前缀/行内反引号保留）。来源：kerb clean_llm_output / llm-json-repair strip_fences / llm-markdown-sanitizer。
- 遗留：前缀清洗保守（仅英文），中文客套未去（避免误伤）。

### R4 单实例守护
- 复盘：多开会导致钩子/配置/历史冲突。
- 方向：QLockFile 单实例。
- 执行：`single_instance.py`（acquire/release）；app.main 启动取锁，失败则提示托盘唤起并退出；锁对象挂 app 防 GC。
- 验证：单测（同路径第二把锁 tryLock=False，释放后可再取）。来源：Qt QLockFile 跨平台+自动处理崩溃残留锁。
- 遗留：真机二次启动弹窗行为待确认。

### R5 Ollama 探活 + 友好提示
- 复盘：选 Ollama 但服务没起时，报错信息不友好。
- 方向：GET /api/tags 探活 + 明确指引。
- 执行：`ollama_probe.py`（is_ollama_up / ollama_models / _tags_url 去 /v1）；overlay `_run_worker` 在 ollama 且未起时提示「先 ollama serve 并拉取模型」。
- 验证：单测（本地 200→True+models；closed port→False；tags_url 归一）。来源：Ollama REST /api/tags 健康检查实践。
- 遗留：模型是否已拉取的细粒度提示可再加。

### R6 窗口定位夹取（多屏/DPI）
- 复盘：screenAt 可能返回 None（PySide6 多显示器已知问题），靠边窗口可能溢出。
- 方向：纯函数夹取 + None 兜底。
- 执行：`util.clamp_position`；overlay `show_at_cursor` 改用它（保留 screenAt None→primaryScreen 兜底）。
- 验证：clamp 单测（左上/右下夹取/区间内不变）。来源：PySide6 多显示器 screenAt 缺陷 + availableGeometry。
- 遗留：真实多屏/高 DPI 行为待真机确认。

### R7 历史搜索 + 导出
- 复盘：历史一多难找、无法外带。
- 方向：搜索过滤 + 导出 JSON。
- 执行：`util.filter_history`；library 历史页加搜索框（实时过滤）+「导出 JSON」按钮（QFileDialog）。
- 验证：filter_history 单测（空/关键词命中）。导出逻辑容错。
- 遗留：导出对话框交互待真机。

### R8 模板变量
- 复盘：模板缺少参数化能力。
- 方向：{{var}} 提取与渲染。
- 执行：`util.extract_vars`/`render_template`；overlay 存模板时提示检测到的变量。
- 验证：单测（中英文变量/去重/渲染/未提供保留）。来源：Zitong {{variable}} 范式。
- 遗留：加载模板时的变量填写 UI 未做（仅提示）。

### R9 版本元信息 + 重打包
- 复盘：exe 无版本信息；需带新依赖重打包。
- 方向：VSVersionInfo + v0.3.0 + 重打包。
- 执行：`version_info.py`（0.3.0.0/FileDescription）；spec EXE 加 `version=`；因安全删除守卫拦 bulk 删除，改用全新 `dist_v3` 输出路径重打包。
- 验证：重打包成功(9.2M)；冻结 exe 启动存活；PowerShell 读元信息 ProductVersion=0.3.0.0、FileDescription=PromptPop 划词提示词优化器。
- 遗留：图标/代码签名未做；旧 dist/ 与 dist_v3/ 并存（守卫拦删除，留待用户清理）。

### R10 回归 + 文档
- 复盘：R2–R9 增量落地。
- 方向：全量回归 + 文档。
- 执行：跑齐三套测试；更新 README/迭代记录。
- 验证：smoke(M1-M4)+test_rounds(上轮)+test_cycle2(本轮) 全过；冻结 v0.3.0 启动存活。
- 结论：本轮可验证目标达成；无新可无头执行方向。

---

## 待确认（需真机/Key）
1. 真机划词取词覆盖率（Electron/游戏/PDF）。
2. Replace/Insert 焦点命中率、单实例二次启动弹窗。
3. 多屏/高 DPI 定位、导出对话框交互。
4. 优化/A-B 实跑需 Key（但 mock e2e 已覆盖链路正确性）。

## 验证汇总
- `py_compile` 全文件通过。
- `tests/smoke_test.py`(M1-M4)、`tests/test_rounds.py`(上轮 2-8)、`tests/test_cycle2.py`(本轮 2-8)：全过。
- 冻结 exe v0.3.0：重打包成功 + 启动存活 + 版本元信息正确。

## 来源
- mock server 测试：openai-python 测试框架(mock server) / respx / pytest-mock
- 输出清洗：kerb clean_llm_output、llm-json-repair strip_fences、llm-markdown-sanitizer
- Ollama 探活：Ollama REST /api/tags 健康检查实践
- 单实例：Qt QLockFile 跨平台防多开
- 多显示器：PySide6 screenAt 缺陷 + availableGeometry
