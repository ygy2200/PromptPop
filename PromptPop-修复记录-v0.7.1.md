# PromptPop 修复记录 · v0.7.1（用户实跑反馈驱动）

触发：用户实际使用后反馈「点击库或者设置的时候会被主页面挡住，还有很多」。
处理方式：先复现定位根因，再通读全部 UI 代码自查，把同类问题一次找齐并修完，
最后用离屏 UI 冒烟测试把「点了没反应 / 被挡住」变成可自动检查的断言。

---

## 根因

主浮窗 `OverlayWindow` 用 `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool` 常驻最前。
在 Windows 下，以它为父窗口、但**自身没有** `WindowStaysOnTopHint` 的对话框会被压在它下面——
表现为点「库」「设置」像没反应，其实窗口已经弹出、只是被主页面盖住了。

统一解法：新增 `promptpop/ui_util.py`，任何由浮窗打开的模态弹窗都先补置顶标志再 `exec()`。

## 修复清单

| # | 问题 | 影响 | 修法 |
|---|---|---|---|
| 1 | **库 / 设置 / 差异视图 / A-B 结果 / 模板命名输入框 / 托盘「设置」被主浮窗挡住** | 点了像没反应 | `ui_util.make_topmost()` + `exec_dialog()`；托盘入口同样处理 |
| 2 | A/B 评估用 `QMessageBox` 显示长评审文本 | 文本截断、**不可选中复制** | 换成 `ui_util.ScrollableResultDialog`（只读文本框 + 复制按钮） |
| 3 | 划词工具条用**自身旧位置**判定所在屏幕，而非选区坐标 | 副屏（尤其左侧副屏 x 为负）会拿主屏边界去夹取，位置跑偏 | 改为 `QApplication.screenAt(QPoint(x, y))` |
| 4 | 结果框只读 | 想微调后再复制/替换却改不了 | 放开可编辑；**流式输出期间临时只读**，避免边看边编辑搅乱内容 |
| 5 | 浮窗尺寸不记忆 | 拖大后下次唤起又回默认大小 | `hideEvent` 保存、`_restore_geometry` 恢复（位置仍跟随光标） |
| 6 | 对话框打开时按热键，浮窗盖到对话框上 | 又变成「被挡住」 | `OverlayWindow._active_dialog`；`show_at_cursor` 发现有待处理弹窗就只提升弹窗 |
| 7 | **Ollama 地址留空会被校验拦住，无法保存设置** | 留空=用默认地址，多数用户都这样 → 一点保存就报错 | 空串视为合法，只对**非空**值做 URL 校验 |
| 8 | 设置里改了热键**必须重启应用**才生效 | 改了像没改 | `SettingsDialog.hotkey_changed` 信号 → `app.restart_hotkey()` 停旧监听器、重新注册 |
| 9 | 设置关闭后，连通性预检线程仍回调已销毁的对话框 | 触发 `RuntimeError: Internal C++ object already deleted` 崩溃 | `SettingsDialog.closeEvent` 断开在跑线程的回调 |
| 10 | 替换/插入失败也照样 `hide()` | 提示一闪而过，用户不知道发生了什么 | 失败时保持窗口打开并提示「已复制到剪贴板，请手动 Ctrl+V」 |
| 11 | 温度输入框标注「0~1」，实际校验是 0~2 | 文案误导 | 标注改为 0~2 |

另：库/设置对话框内部的消息框也统一走 `ui_util.exec_message / exec_warning`，避免连锁被挡。

## 改动文件

- 新增：`promptpop/ui_util.py`、`tests/test_ui_smoke.py`
- 修改：`promptpop/{overlay,settings_dialog,library_dialog,toolbar,app}.py`

## 验证

新增离屏 UI 冒烟测试 `tests/test_ui_smoke.py`（10 项，全部通过）：

1. 六类弹窗经 `make_topmost` 后均带 `WindowStaysOnTopHint`
2. 浮窗/设置/库/工具条**所有可用按钮均已连接处理函数**（直接抓「点了没反应」）
3. 结果框可编辑
4. 有弹窗时只提升弹窗、浮窗不抢前；弹窗关闭后回归正常
5. 工具条贴边坐标被夹回屏幕内
6. 浮窗尺寸记忆（隐藏保存、重建恢复）
7. Ollama 地址留空可正常保存
8. 改热键发出 `hotkey_changed` 信号
9. 关闭设置会断开在跑的预检回调
10. 替换失败保持窗口打开并提示手动粘贴

回归：**八套测试全绿**（smoke / rounds / cycle2 / cycle3 / cycle4 / cycle5 / cycle6 / ui_smoke）。
打包：单文件 exe 核验启动存活 + 版本元信息 `0.7.1.0`。

> 测试侧踩坑记录：PySide6 的 `QObject.receivers` 只认 Qt 内部规范化签名
> （`"2clicked(bool)"`），`"clicked()"` 一律返回 0——差点把「按钮没接线」误报成产品缺陷。

## 仍待真机确认（离屏无法验证）

1. 置顶弹窗在**多屏 + 不同 DPI**下的实际层级表现。
2. 热键重新注册后，旧组合键是否真的完全释放（pynput `stop()` 的实时性）。
3. 替换/插入的焦点命中率（依赖前台窗口恢复）。
4. 全局热键与系统/其它软件热键冲突（纯 pynput 无原生探测）。
