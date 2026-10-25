# PromptPop v0.7.3 — 体验优化迭代记录（10 轮循环）

> 目标：在 v0.7.2 基础上继续找问题、提升体验；每轮结合软件内自查 + 网络/GitHub 调研。
> 调研依据：独立调研报告（同类工具 PopClip / Raycast / QDuo / AIA-selection-assistan、PySide6 置顶窗坑、Windows 全局热键 RegisterHotKey 最佳实践、跨应用取词/回填三路降级、httpx/LLM 流式重试与取消）+ 二次独立代码审查（14 条）。

---

## 一、10 轮总览

| 轮次 | 主题 | 状态 |
|---|---|---|
| R1 | 热键注册失败可见化 + 自定义热键风险校验 | ✅ |
| R2 | 剪贴板还原保真（完整 MIME 快照） | ✅ |
| R3 | 划词监听降噪（程序黑名单） | ✅ |
| R4 | 输入超长防护（可配置上限） | ✅ |
| R5 | 错误反馈升级（状态栏颜色分级） | ✅ |
| R6 | 多提供商扩展（自定义 OpenAI 兼容端点） | ✅ |
| R6b | 「检查更新」→ 取消（无真实 release 源，必然失败） | 记录在案 |
| R7 | 二次独立审查 + 修复（14 条） | ✅ |
| R8 | 取词阻塞缓解（延时可配置 + 300ms 去重） | ✅ |
| R9 | 对话框键盘可达性（默认按钮 / Esc / ✕） | ✅ |
| R10 | 收尾：全量回归 + 打包 v0.7.3 | ✅ |

---

## 二、R1–R6 改进明细

### R1 热键
- `util.check_hotkey_risk(combo)`：拦截 Windows 系统占用的 Win+ 组合（Win+L 锁屏等，注册也收不到）；含 Space 组合（Ctrl+Shift+Space，易与输入法冲突）给非阻断风险提示。
- `settings_dialog._save`：保留组合直接拦保存；风险提示改为**输入框旁实时标签**（`_update_hotkey_hint`），不在保存时弹模态框。
- `app.main`：`hotkey_state["active"]` 如实反映注册状态——失败则状态栏提示「请用托盘菜单唤起」，不再谎报。

### R2 剪贴板保真
- `capture._clipboard_snapshot()` / `_clipboard_restore_full()`：完整克隆当前剪贴板**所有 MIME 格式**（含 Office 私有格式/图片），`extract_clipboard` 在 `finally` 原样还原；快照失败回退 text+html。

### R3 划词降噪
- `config.selection_exclude_programs`（默认 `["explorer","dopusrt","dllhost"]`）+ `capture.should_capture_selection()`：文件管理器等「拖拽」多为移动文件，跳过取词，避免误触发剪贴板抖动/工具条误弹。

### R4 输入超长防护
- `config.max_input_chars`（默认 20000，0=不限制）；`overlay._on_optimize` / `_on_iterate` / `_on_ab` 三条入口提交前校验，超限状态栏 warn 提示并拦截。
- `set_input` / `_on_library_load` 的硬编码 `[:8000]` 截断改为遵循该配置，截断时明确提示。

### R5 错误反馈分级
- `overlay._status(msg, kind)`：error=红 / warn=黄 / ok=绿 / info=主题默认色。失败、取消、超长、缺 Key、Ollama 未运行均用对应级别，不再混在普通信息里。

### R6 多提供商扩展
- `providers.get_all_providers / add_custom_provider / remove_custom_provider / resolve`：支持用户添加任意 **OpenAI 兼容端点**（OpenRouter / 本地 vLLM / 自建网关）。
- `settings_dialog` 新增「自定义端点」标签页（增/删 + 名称/Base URL/默认模型/Key/是否需要 Key）；浮窗与设置的 provider 下拉均合并自定义端点。

---

## 三、R7 二次独立审查 + 修复（14 条）

独立审查者对 R1–R6 后代码二次审查，返回 14 条问题，处置如下：

| # | 严重度 | 问题 | 处置 |
|---|---|---|---|
| 1 | 必崩 | `settings_dialog.closeEvent` 把 `_ping_thread` 置 None → 释放运行中 QThread 最后一个引用 → 进程 abort | **已修**：只断开信号；`_on_ping` 加 `finished→deleteLater`；`_on_ping_result` 不再 deleteLater |
| 2 | 功能失效 | 划词流程不记录来源窗口 → 工具条「优化」时前台已是浮窗自己 → 替换粘回自己输入框 | **已修**：新增 `toolbar.source_hwnd`（on_selection 存 fg），`toolbar_optimize` 优先使用 |
| 3 | 功能失效 | `set_input`/`_on_library_load` 硬编码 `[:8000]` 截断且无提示 | **已修**：遵循 `max_input_chars`，截断时 warn 提示 |
| 4 | 功能失效 | A/B 评估在浮窗隐藏时结果永久丢失（用户已花过钱） | **已修**：`_pending_judge` 保存结论，`show_at_cursor` 显示后补弹 |
| 5 | 功能失效 | 设置「取消」不撤销端点增删，后续任意 save 静默落盘 | **已修**：`__init__` 深拷贝快照，`reject()` 还原 |
| 6 | 功能失效 | `insert_after` 无选区时发 Right 键 → 光标偏移一位，插到错误位置 | **已修**：`_has_text_selection()`（UIA best-effort，失败保守返回 True），无选区则直接粘贴 |
| 7 | 功能失效 | 替换/插入恒返 True 的假成功（焦点被抢时提示已替换实际没粘上） | **已修**：`_send_ctrl_v()` 后 sleep 0.12s 再比对 `GetForegroundWindow() == owner_hwnd` |
| 8 | 必崩（新环境） | `secrets.py` 顶层硬 `import keyring`，而 requirements.txt 未声明 → 干净安装后启动即崩 | **已修**：惰性导入，无 keyring 时 `set_key` 返回 False、回退 config 明文；requirements.txt 补 `keyring>=24.0` |
| 9 | 体验 | 取词主线程 sleep 0.24~0.56s 冻结（UIA 失败走剪贴板回退时） | **部分**：R8 已把延时改为可配置 + 300ms 去重；根治需改信号驱动，**待真机** |
| 10 | 体验 | Ollama 探测每次同步阻塞满 3s | **已修**：10s TTL 缓存（只缓存「可达」） |
| 11 | 数据安全 | 配置损坏即静默全重置 + 非原子单备份 | **已修**：`load` 损坏时从 `.bak` 恢复；`save` 改「临时文件 + replace」原子写 |
| 12 | 功能失效 | Key 保存失败被静默忽略（用户以为存了，下次报未配置） | **已修**：`_save` 检查 `set_key` 返回值，失败即警告并阻止 accept |
| 13 | 体验 | 工具条无手动关闭、失焦不收起 | **已修**：补 ✕ 按钮 + 失焦即 hide + `hideEvent` 停定时器 |
| 14 | 健壮性 | ModelFetcher 无 `finished→deleteLater`（与 PingThread 收尾不统一） | **已修**：补上，统一生命周期模式 |

**审查遗留（权衡不加，已标注）**：`open_settings` 中 `dlg` 为局部变量，exec 返回即销毁；若此刻 ping 仍在飞行中，随对话框释放的线程引用仍有析构风险。建议真机验证「测试连接 → 立即关闭设置」。最稳收尾是 `closeEvent` 里 `th.quit(); th.wait(3000)`，但 wait 会阻塞 UI 线程至 3s，权衡后暂不加。

---

## 四、R8–R9

- **R8**：`capture.pick_clipboard_delay()` 纯函数（`clipboard_delay_default` / `clipboard_delay_slow` 可配，默认值不变避免回归）；`app.on_selection` 加 300ms 同坐标去重，避免连续拖选叠加主线程冻结。
- **R9**：`overlay._on_diff` 差异视图补 default 按钮（Enter 关闭）+「复制差异」按钮；`library_dialog` 「关闭」设为 default。

---

## 五、测试增量

| 套件 | 新增 |
|---|---|
| `test_ui_smoke.py` | 17 项：弹窗置顶 / 按钮接线 / 结果可编辑 / 热键不抢前 / 工具条判屏 / 尺寸记忆 / 空地址可保存 / 热键变更信号 / 关闭不断 ping 引用 / 替换失败保窗 / 快捷键真实触发 / 尺寸跨重启 / **剪贴板快照保真** / **状态栏颜色分级** / **自定义端点进下拉** / **对话框默认按钮** / **输入超长守卫（三入口）** / **设置取消还原快照** |
| `test_cycle5.py` | +4：check_hotkey_risk / should_capture_selection / config migrate 保留新键 / pick_clipboard_delay |
| `test_cycle6.py` | +5：自定义端点 get/add/remove/resolve / secrets 惰性导入 / config 原子写+损坏恢复 / ollama 探测缓存 |

**回归**：8 套全绿。

**测试自身缺陷修复**：`test_cycle2/3/4/5` 起 `OptimizeWorker` 后从不 `quit/wait`，并行跑套件时进程退出瞬间打印 `QThread: Destroyed while thread is still running`。已 4 处统一补 `w.quit(); w.wait(3000)`。此为测试缺陷，非产品缺陷（产品侧 engine 已有 `finally close`，worker 由 overlay 持有）。

---

## 六、产物与回滚

- 版本：`0.7.3`（`promptpop/__init__.py` + `version_info.py` 已同步）
- 打包：`PromptPop-onefile.spec --distpath dist_v73 --workpath build_v73`
- 桌面 exe：`C:/Users/y/Desktop/PromptPop.exe`（版本元信息 0.7.3.0）
- 迭代日志：`ITERATION_OPT_LOG.md`
- 旧版回滚：`PromptPop/dist_v72/PromptPop.exe`（v0.7.2.0）拷回桌面即可

## 七、仍待真机确认

1. 浮窗快捷键实机响应（Ctrl+D / Ctrl+I / Ctrl+R / Ctrl+Shift+C）。
2. 替换/插入焦点命中率（R7 #7 新增粘贴后前台校验）。
3. 取词主线程瞬时阻塞（R7 #9，仅 UIA 失败走剪贴板回退时）。
4. 「测试连接 → 立即关闭设置」的 QThread 析构（R7 #1 遗留注意）。
5. 自定义端点 UI 增删易用性、A/B 隐藏后补弹。
