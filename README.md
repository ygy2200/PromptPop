# PromptPop — 划词提示词优化器 (v0.7.10)

选中任意文字 → 弹悬浮窗 → 一键把口语化指令优化成**结构化、agent 友好**的提示词 → 贴回原处。

## 运行
1. 安装依赖：`pip install -r requirements.txt`
2. 启动：`python main.py`
3. 首次点浮窗右上角「设置」填 DeepSeek / OpenAI API Key（或填 Ollama 地址用本地模型）
4. 三种用法：
   - **划词即优化**：在任意 App 拖选文字 → 弹出小工具条 → 点「✨ 优化提示词」
   - **热键唤起**：选中/复制后按 `Ctrl+Shift+Space` → 浮窗自动预填剪贴板
   - **手动输入**：直接在浮窗输入框粘贴指令 → 点「优化 ✨」
5. 结果流式显示 →「复制」/「替换 Replace」（恢复原窗口焦点并粘贴回去）/「存为模板」/「迭代 ↻」

## 功能（v0.7.3）
- 无边框/置顶/可拖拽浮窗；暗 / 亮主题
- 系统级划词：鼠标钩子检测拖选 + UIA / 剪贴板回退取词（设置里可关）
- 取词安全：总是备份还原剪贴板(含富文本)、Ctrl+Insert→Ctrl+C 两段式、光标形状降智、全屏游戏跳过、逐应用 fine-tuned
- 内嵌 meta-prompt 引擎：DeepSeek / OpenAI / Ollama 统一走 OpenAI 兼容协议；LangGPT 结构化输出
- 双模式：优化用户指令 / 优化系统提示词；meta-prompt 可自定义；风格变体（标准/精简/严格）
- 请求超时、可取消、仅瞬时错误重试
- 结果动作：复制 / 替换 Replace / 插入 Insert / 评估 A/B / 存为模板
- 多轮迭代；历史 + 模板库（SQLite，「库」按钮）
- API Key 存系统钥匙串（keyring，启动自动迁移明文）
- 托盘常驻；开机自启（Windows，设置里开）；入口异常落 crash.log
- Ollama 探活：本地模型没起时给出明确指引
- 结果自动清洗：去 ``` 围栏 / 英文客套前缀后再显示与入库
- 单实例守护（防多开）；历史搜索 + 导出 JSON；模板 {{var}} 变量提示
- 模型下拉可编辑 + 「⟳」一键拉取可用模型；完成状态显示 token 用量
- 报错脱敏（不泄露 API Key）；设置保存前校验温度/地址；程序化托盘图标；Ctrl+Enter 优化 / 重新生成
- **网络代理支持**：设置里填 HTTP 代理，访问 DeepSeek/OpenAI 更稳（httpx 0.28 `proxy=`）
- **报错可读化**：按错误类别给出中文指引（网络/鉴权/参数/未知），且不泄露 API Key
- **配置自动迁移**：旧版配置启动自动补默认、剔未知键、写版本号（幂等、非 dict 安全）
- **调试日志**：可开关的 RotatingFileHandler，写盘前脱敏 API Key
- **历史治理**：固定重要项(pinned) / 按保留天数清理未固定 / 单条删除
- **Esc 取消**：流式优化进行中按 Esc 即取消并隐藏浮窗
- **浮窗可缩放**：无边框浮窗三向 QSizeGrip 拖拽缩放
- **超时拆分**：连接/读取超时分离（connect 10s / read 60s），流式长生成不再被误杀
- **安全重试**：仅「未收到任何 token 的连接阶段」失败才重试，避免流式生成一半重复计费；中段失败保留已生成内容并提示
- **热键可自定义**：设置里改唤起组合键（Ctrl+Shift+Space / Ctrl+Alt+K 等），保存时校验并归一化
- **配置导入/导出 + 自动备份**：设置可导出/导入配置；保存前自动备份 `config.json.bak`
- **超大窗口夹取**：浮窗大于屏幕时自动居中，避免溢出
- **历史导出 Markdown**：库对话框可把历史导出为 MD 分享/存档
- **成本估算**：完成态按模型价目表追加估算费用（≈$x.xxxx）
- **高 DPI 适配**：`PassThrough` 精确缩放 + 高清图标，125%/150% 屏不再过大或模糊
- **meta-prompt 升级 CRAFT + ICE**：能力/角色/任务/格式/语气 五维 + 上下文/示例/约束；支持传入额外上下文（受众、排除项等，任意键）
- **固定历史接通（v0.7.10）**：库对话框「固定/取消固定」+ 📌 标记（pin_history 此前零调用，README 宣称的固定项无法触达，第四例死功能）
- **busy 状态机加固（v0.7.10）**：优化进行中打开库/本地整理被拦截（实测内容与流式 token 混合）；设置面板多入口连点不叠开
- **流式显示缓冲（v0.7.10）**：token 攒批 60ms 刷新——修复逐 chunk 插入 O(n²)（实测 1MB 显示 153s → 数秒内）
- **托盘「关于」+ 打开配置目录（v0.7.10）**：版本号与配置/日志目录不再靠翻文档找
- **配置迁移矩阵（v0.7.10）**：31 字段 × 10 坏值 = 310 组合攻击零崩溃（固化防回归）
- **配置坏值防御（v0.7.9）**：配置被手改成坏值（"abc" 温度、负超时、非 list 端点表）不再让取词/优化/启动崩——safe_int/safe_float 统一兜底；顺带修复「0 温度被 or 语义悄悄变成 0.3」
- **对抗性回归 adv_*（v0.7.9）**：6 个攻击测试文件（配置坏值矩阵/SQL 注入/超长与控制字符/恶意围栏/畸形 URL/线程并发），按 AGENTS.md 对抗性验证要求固化
- **错误对象防御（v0.7.9）**：__str__ 抛异常的第三方异常不再炸 worker 线程；负超时夹取到 ≥1s
- **热键保留表修复（v0.7.9）**：Win+Space/Win+Tab（validate 尖括号形态）此前拦不住；中文单字（如 Ctrl+加）不再被接受为键名
- **清除已存 API Key（v0.7.9）**：设置面板 Key 行新增「清除」按钮（此前留空=不修改，钥匙串 Key 无法删除）
- **自定义端点编辑（v0.7.9）**：设置「自定义端点」可编辑选中项（此前只能删了重加）；Key 留空保留原 Key
- **模板编辑（v0.7.8）**：库对话框可编辑选中模板内容（名称/分类不动），不再「写错只能删了重存」
- **模板变量填空（v0.7.8）**：加载含 {{var}} 的模板时逐个询问填值（留空/取消保留占位符）——render_template 此前无生产调用方，变量只能提示不能填
- **模板编辑（v0.7.8）**：库对话框可编辑选中模板内容（名称/分类不动），不再「写错只能删了重存」
- **载入默认 meta-prompt（v0.7.8）**：设置「优化模板」tab 一键载入内置默认，微调而非从零写
- **历史容量（v0.7.8）**：列表/导出上限 200→1000 条，触顶时窗口标题明示
- **错误分类 422（v0.7.8）**：openai UnprocessableEntityError 归 invalid（原先落 unknown 被误导成「需配代理」）
- **迭代分隔加固（v0.7.8）**：多轮迭代改用 XML 风格分隔，结果含 `"""` 不再截断格式
- **附加约束输入框（v0.7.7）**：浮窗输入框下方可填受众/语言/排除项等，随优化与迭代请求一并交给模型（此前 context 仅 API 层可用、UI 不可达）；自定义 meta-prompt 未写 `{ctx}` 占位符时约束追加到尾部而非静默丢弃
- **A/B 评审输出格式收死**（v0.7.7）：固定五行评分（结构化/可执行性/约束清晰度/忠实原意/结论），不再受模型自由发挥影响
- **差异视图（Ctrl+D）**：行级对比「原文 vs 优化结果」（+ 新增 / - 移除）
- **连通性预检**：设置页「测试连接」异步探测服务是否可达（不消耗 token）
- **历史标签**：可给历史打标签、按标签检索、导出 Markdown 带标签
- **模板导入/导出**：模板库整体导出为 JSON / 导入（同名跳过）
- **浮窗快捷键**：Ctrl+Enter 优化 · Ctrl+D 差异 · Ctrl+I 插入 · Ctrl+R 替换 · Ctrl+Shift+C 复制 · Esc 取消
- PyInstaller 打包 exe（含版本元信息）

## 架构（分层）
| 层 | 文件 | 说明 |
|---|---|---|
| 捕获 | `capture.py` | 鼠标钩子判拖选；UIA(uiautomation)→剪贴板回退取词；`SelectionMonitor` 后台监听 |
| 引擎 | `engine.py` `meta_prompt.py` `providers.py` | OpenAI 兼容协议统一三家；LangGPT meta-prompt；QThread 流式 |
| 动作 | `actions.py` | 恢复前台焦点 + 写剪贴板 + 模拟 Ctrl+V 实现 Replace |
| UI | `overlay.py` `settings_dialog.py` `library_dialog.py` `toolbar.py` `app.py` | 浮窗 + 设置 + 库 + 划词工具条 + 托盘/热键 |
| 存储 | `config.py` `history.py` | JSON 配置 + SQLite 历史/模板 |
| 支撑 | `hotkey.py` `threads.py` `ui_util.py` `secrets.py` `debuglog.py` | 全局热键 / 线程注册表 / 置顶弹窗与全局主题 / 钥匙串 / 调试日志 |

## 打包

两种产物，按需选：

```bash
# 单文件（一个 exe，可直接放桌面 / 拷走）——冷启动需解压依赖约 3-8 秒
pyinstaller PromptPop-onefile.spec --noconfirm --distpath dist_v710 --workpath build_v710
# 产物： dist_v710/PromptPop.exe（约 68 MB，版本元信息 0.7.10.0）
# spec 已排除 sklearn/scipy/matplotlib 等无关重库，且禁用 UPX（压坏 Qt DLL 会导致窗口不渲染）
```
最新构建可到 GitHub Releases 下载（见仓库页），桌面部署直接复制 exe 即可。

## 已知限制 / 待确认
- **成本估算按 2025 年单一价目**（PRICE_TABLE）；DeepSeek 2026 年起为峰谷分时 + 缓存命中分级定价（api-docs.deepseek.com/quick_start/pricing），估算仅供量级参考，未知模型不显示成本
- 划词取词对 Electron/游戏/PDF 的真实覆盖率待真机确认（退化为剪贴板回退，个别应用仍可能取空）
- IAccessible 层暂缓（剪贴板回退已覆盖多数老应用）；是否投入待确认
- Replace/Insert 焦点恢复在不同 App 的命中率待真机确认
- A/B 评估与优化实跑需配置 API Key
- 仅 Windows 完善；macOS/Linux 需再适配（UIA/自启为 Windows 专有）

## 测试
```
QT_QPA_PLATFORM=offscreen python tests/smoke_test.py      # M1-M4 回归
QT_QPA_PLATFORM=offscreen python tests/test_rounds.py     # 第一轮 R2-R8 单测
QT_QPA_PLATFORM=offscreen python tests/test_cycle2.py     # 第二轮：mock LLM 端到端(无需 Key)+纯函数
QT_QPA_PLATFORM=offscreen python tests/test_cycle3.py     # 第三轮：模型列表/token用量/脱敏/校验/重试端到端
QT_QPA_PLATFORM=offscreen python tests/test_cycle4.py     # 第四轮：代理/错误指引/配置迁移/调试日志脱敏/历史治理/Esc/缩放
QT_QPA_PLATFORM=offscreen python tests/test_cycle5.py     # 第五轮：超时拆分/安全重试/热键/配置导入导出/夹取/历史MD/成本/迁移
QT_QPA_PLATFORM=offscreen python tests/test_cycle6.py     # 第六轮：高DPI/CRAFT-ICE/差异视图/ping/历史标签/模板导入导出/快捷键
QT_QPA_PLATFORM=offscreen python tests/test_meta_ctx.py    # meta-prompt 上下文/judge 格式
QT_QPA_PLATFORM=offscreen python tests/test_engine_cancel.py  # 重试退避中取消
QT_QPA_PLATFORM=offscreen python tests/test_config_import_guard.py  # 导入坏配置守卫
QT_QPA_PLATFORM=offscreen python tests/test_library_tag.py  # 打标签回归（text=→default=）
QT_QPA_PLATFORM=offscreen python tests/test_template_vars.py  # 模板变量填空
QT_QPA_PLATFORM=offscreen python tests/test_round5_ui.py   # 第五轮 UI（历史上限/载入默认模板/模板编辑）
QT_QPA_PLATFORM=offscreen python tests/test_round6_ui.py   # 第六轮 UI（重入防御/清除Key/MD围栏/端点编辑/滚动）
QT_QPA_PLATFORM=offscreen python tests/adv_config.py       # 对抗：配置坏值矩阵/迁移攻击/端点类型
QT_QPA_PLATFORM=offscreen python tests/adv_history.py      # 对抗：SQL注入/超长文本/同名轰炸
QT_QPA_PLATFORM=offscreen python tests/adv_util.py         # 对抗：畸形热键/负尺寸/diff边界
QT_QPA_PLATFORM=offscreen python tests/adv_text.py         # 对抗：恶意围栏/1MB文本/深嵌套JSON
QT_QPA_PLATFORM=offscreen python tests/adv_engine.py       # 对抗：畸形URL/负超时/str炸裂异常
QT_QPA_PLATFORM=offscreen python tests/adv_threads.py      # 对抗：线程注册表并发
QT_QPA_PLATFORM=offscreen python tests/adv_dataflow.py     # 对抗：坏配置真实启动链/模板全链路/极端输入
QT_QPA_PLATFORM=offscreen python tests/test_round7_ui.py   # 第七轮 UI（固定历史/busy拦截/关于/设置守卫）
QT_QPA_PLATFORM=offscreen python tests/test_stream_buffer.py  # 流式缓冲（O(n²) 性能回归守卫）
QT_QPA_PLATFORM=offscreen python tests/test_ui_smoke.py    # UI 冒烟：弹窗置顶/按钮接线/结果可编辑/尺寸记忆/热键不抢前/空地址可保存
                                                     #   + 状态栏颜色分级/自定义端点/默认按钮/输入超长守卫/剪贴板快照保真
```
