# PromptPop 修复记录 · v0.7.2（独立代码审查驱动）

触发：v0.7.1 发布后，派独立审查者逐行审完全部 UI 代码，返回 18 条缺陷。
其中数条是**硬伤**（README 宣称的浮窗快捷键在 Windows 下完全失效）。
本批次把能指认、可复现的全部修完，并补回 v0.7.1 漏掉的两条。

---

## 关键硬伤

| # | 问题 | 影响 | 修法 | 对应审查项 |
|---|---|---|---|---|
| 1 | **浮窗快捷键 Ctrl+D/I/R/Shift+C 全部失效** | Windows 下按 Ctrl 时 `QKeyEvent.text()` 返回控制字符（`Ctrl+D`→`\x04`），永远匹配不上 → README 写的快捷方式除 Esc 外全无反应 | 改用 `e.key()` 映射 `Qt.Key_D/R/I/C`，`resolve_overlay_shortcut` 收键名 | 3 |
| 2 | **尺寸记忆重启即失效** | `_remember_geometry` 写 `window_width/height`，但这两个键不在 `DEFAULT_CONFIG`，`migrate()` 当未知键丢弃 | 把 `window_width/window_height` 加进 `DEFAULT_CONFIG`（默认 0=用默认大小） | 5 |
| 3 | **ModelFetcher / PingThread 连点崩溃** | 每次点「⟳」/「测试连接」用新对象覆盖旧引用，旧 QThread 失去 Python 引用被析构 → "Destroyed while thread is still running" + abort | `isRunning()` 守卫，跑着就不新建；PingThread 结束 `deleteLater`、回调前 `isVisible()` 判活 | 1,2 |
| 4 | **httpx 客户端持续泄漏** | 每次请求 `build_client` 新建对象从不关闭，反复优化泄漏 socket/连接池 | `finally: client.close()`（run 内与 `list_models`） | 12 |
| 5 | **取消不即时** | `cancel()` 只置 `_stop`，卡在连接/重试退避时线程还能跑几十秒，期间「优化中」卡死、按钮静默失效 | 加 `_stop_event`，退避等待改为 `_stop_event.wait`，cancel 立即打断 | 14 |
| 6 | **替换/插入恒返回 True** | 不校验原窗口是否还在 / 粘贴是否真发生，粘到桌面或自己窗口也报「已替换」后立刻 hide | 校验 `IsWindow` + 粘贴后比对前台窗口，失败返回 False 走「已复制」分支 | 9 |

## 状态机 / 体验

| # | 问题 | 修法 | 审查项 |
|---|---|---|---|
| 7 | 后台任务在跑时再点优化**静默无反应** | guard 命中时 `_status("上一条请求还在处理中…")`；`btn_regen` 纳入 `_set_busy` 禁用 | 7 |
| 8 | 迭代/重新生成**失败会丢掉上一版结果** | 发请求前存 `_prev_result`，`_on_failed`/`_on_cancelled` 回填 | 8 |
| 9 | 浮窗已隐藏时仍**凭空弹出 A/B 评估框** | judge 完成若浮窗不可见先存 `_judge_result`，`show_at_cursor` 时补弹 | 10 |
| 10 | 设置校验失败造成**半保存**（Key 已写钥匙串） | 把所有校验提前到任何 `config.set` 之前，校验不过直接 return | 11 |
| 11 | 工具条**永久挡视线**（无自动消失） | 加 `QTimer` 单次自动隐藏（5s）+ 失焦/离开即隐藏 + ✕ 按钮 | 16 |
| 12 | 库导出**忽略搜索过滤**（导全部却报过滤后数量） | 导出当前过滤结果 `self._hist` | 17 |
| 13 | 右上角 QSizeGrip **压住 ✕ 关闭按钮** | 去掉右上 grip，只留右下/左下 | 18 |
| 14 | 浮窗里换提供商**冲掉手填自定义模型名** | 检测到手填模型（非默认）则保留，不覆盖 | 次要 |
| 15 | 空结果时 `iter_row` 提前可见、按钮全灰 | 把 `setVisible(True)` 移到空判断之后 | 次要 |
| 16 | 库对话框内部 `QInputDialog` 不走置顶统一入口 | 换成 `ui_util.get_text` | 次要 |

## v0.7.1 漏补两条（本轮补上）

| # | 问题 | 修法 |
|---|---|---|
| 17 | **取词把浮窗自己记成 owner** → 浮窗已聚焦时再按热键/点托盘「显示」，点「替换」会把结果粘进自己输入框 | `app._pick_owner_hwnd()` 排除 `overlay/toolbar` 自身 hwnd，命中则保留上一次真实来源 |
| 18 | **在浮窗自己输入框里选字也会弹工具条**（自干扰） | `on_selection` 里前台 hwnd 是自身窗口则跳过 |

## 改动文件

- 修改：`promptpop/{overlay,settings_dialog,library_dialog,toolbar,app,engine,config,actions,capture}.py`
- 新增测试项：`tests/test_ui_smoke.py`（尺寸记忆跨重启断言等）

## 验证

- 八套测试全绿（smoke / rounds / cycle2 / cycle3 / cycle4 / cycle5 / cycle6 / ui_smoke）。
- `test_cycle2` 单实例项此前因上一次被 kill 的进程残留锁文件偶发失败，清锁后稳定通过（非产品回归）。
- 快捷键修复为 Windows 平台行为（离屏 `e.key()` 路径已编译校验；按键映射逻辑走纯函数，单测覆盖）。

## 仍待真机确认（离屏无法验证）

1. 浮窗快捷键在实际 Windows 下的真实按键响应（依赖 `e.key()` 在非离屏环境的派发）。
2. 取词主线程阻塞 / 剪贴板清空：仅当 UIA 取词失败走剪贴板回退时发生，
   且已备份还原；本次仅修了"自身窗口自触发"那部分，跨程序拖拽的瞬时阻塞属既有设计权衡，未做大改。
3. 替换/插入焦点命中率（依赖前台窗口恢复 + 用户授权）。
