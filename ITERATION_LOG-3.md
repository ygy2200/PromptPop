# PromptPop 迭代记录 · 第三轮 10 轮（v0.3.0 → v0.4.0）

> 承接前两轮（ITERATION_LOG.md / ITERATION_LOG-2.md）。重点补**可验证 UX / 安全 / 健壮性**。每轮固定字段：复盘结论 / 下一步方向与优先级 / 执行结果(验证+来源) / 遗留问题。无头不可验证项标「待确认」。不碰 agenthub。

## 关键假设（首轮前）
- 继续补「无头可验证」的增量；优先模型列表、token 用量、Key 防泄露、设置校验、托盘图标、重试端到端证明。
- 真实硬件/真实 Key 项标待确认。

---

### R1 复盘 + 调研
- 复盘：v0.3.0 已无 Key 端到端可验；仍缺模型发现、用量可见、Key 防泄露、设置校验、托盘图标、重试的行为证明。
- 方向：检索 models.list / include_usage / 脱敏 / QPixmap 图标。
- 执行：确定用 `client.models.list()`、`stream_options include_usage`、脱敏替换、QPixmap+QPainter 画图标。
- 遗留：进入实现。

### R2 模型列表 + 下拉
- 复盘：模型靠手输，易错、不知有哪些。
- 方向(高优先)：拉取 /models 填充可编辑下拉。
- 执行：`engine.list_models`；overlay 模型改可编辑 QComboBox + 「⟳」按钮 + `ModelFetcher`(QThread 后台拉取防卡 UI)。
- 验证：`list_models` 对 mock /v1/models 返回列表；overlay `_on_models_fetched` 填充并保留当前项。来源：OpenAI 兼容 /models（openai SDK `client.models.list()`）。
- 遗留：个别端点不支持 /models 时退化为手动输入（已提示）。

### R3 token 用量显示
- 复盘：看不到花了多少 token。
- 方向：include_usage + 状态栏显示。
- 执行：`consume_stream` 增 `on_usage`；worker 请求 `stream_options include_usage` 并发 `usage` 信号；overlay 完成状态追加 tokens。
- 验证：mock 尾附用量块 → worker.usage total_tokens=19 断言通过。来源：OpenAI cookbook stream_options include_usage（末块带 usage、choices 空）。
- 遗留：流中断可能收不到用量（已知，SDK 行为）。

### R4 Key 防泄露
- 复盘：报错/日志可能带出 Key。
- 方向：脱敏。
- 执行：`util.mask_secret/scrub_secret`；worker 发 failed 前把 Key 替换为脱敏串。
- 验证：`scrub_secret` 单测；worker 对坏 base_url+独特 Key 失败，断言失败信息不含该 Key。来源：密钥脱敏最佳实践（redaction in logs/errors）。
- 遗留：无。

### R5 设置校验
- 复盘：温度/地址可填非法值。
- 方向：保存前校验。
- 执行：`util.validate_temperature/validate_base_url`；settings `_save` 校验不过则弹框不保存。
- 验证：校验纯函数单测（合法/非法/越界）。来源：参数校验常规实践。
- 遗留：无。

### R6 托盘图标
- 复盘：无图标文件，托盘/任务栏图标空白。
- 方向：程序化绘制图标。
- 执行：`app.make_icon`（QPixmap+QPainter 画圆角方块+`P`）；托盘 + 浮窗 setWindowIcon。
- 验证：`make_icon().isNull()` 为 False。来源：PySide6 QPixmap/QPainter 绘制图标范式。
- 遗留：真实系统托盘渲染待确认。

### R7 快捷键 + 重新生成
- 复盘：只能点按钮。
- 方向：Ctrl+Enter 优化 + 重新生成。
- 执行：overlay keyPressEvent 加 Ctrl+Enter→优化；action 行加「重新生成」→重跑优化。
- 验证：overlay 端到端（mock）验证重新生成触发 worker 并出结果。来源：桌面工具快捷键常规。
- 遗留：无。

### R8 重试端到端证明 + 5xx 归类修正
- 复盘：第一轮加了瞬时重试，但无端到端证明；且 5xx 未归为可重试。
- 方向(高优先)：mock 瞬时失败证明重试恢复；修 5xx 归类。
- 执行：engine `_transient_errors` 增 `InternalServerError`；mock 加 `fail_first`；测试 503→重试→成功。
- 验证：`test_cycle3` R8：fail_first=1 → worker max_retries=2 → done 含内容。来源：仅重试超时/连接/限流/5xx，勿重试 content-filter/invalid。
- 遗留：无。

### R9 打包 v0.4.0
- 复盘：带新代码+图标重打包。
- 方向：version_info 0.4.0.0 + 重打包。
- 执行：更新 version_info；全新 dist_v4 打包。
- 验证：重打包成功(9.2M)；冻结 exe 启动存活；ProductVersion=0.4.0.0。
- 遗留：旧 dist*/ 并存（守卫拦删除）。

### R10 回归 + 文档
- 复盘：R2–R9 落地。
- 方向：全量回归 + 文档。
- 执行：跑齐四套测试；更新 README/记录。
- 验证：smoke/rounds/cycle2/cycle3 全过；冻结 v0.4.0 启动存活。
- 结论：本轮可验证目标达成；无新可无头执行方向。

---

## 待确认（需真机/Key）
1. 真机划词取词覆盖率（Electron/游戏/PDF）。
2. Replace/Insert 焦点命中率、单实例二次启动弹窗、系统托盘渲染。
3. 多屏/高 DPI 定位、模型列表在各真实端点的支持度。
4. 优化/A-B 实跑需 Key（mock 已覆盖链路正确性）。

## 验证汇总
- `py_compile` 全文件通过。
- 四套测试全过：smoke(M1-M4)/test_rounds(轮1)/test_cycle2(轮2)/test_cycle3(轮3，含 token 用量/无 Key 泄露/503 重试端到端/模型拉取/重新生成)。
- 冻结 exe v0.4.0：重打包成功 + 启动存活 + 版本元信息正确。

## 来源
- OpenAI 兼容 /models：openai SDK `client.models.list()`
- token 用量：OpenAI cookbook `stream_options include_usage`
- 密钥脱敏：redaction in logs/errors 最佳实践
- 托盘图标：PySide6 QPixmap+QPainter 绘制
- 重试策略：仅重试超时/连接/限流/5xx
