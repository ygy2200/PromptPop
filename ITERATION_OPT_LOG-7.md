# PromptPop 优化迭代日志 · 第七轮 50 轮循环（v0.7.10）

> 执行：zcode，2026-10-25。承接第六轮（v0.7.9）。50 轮分配：
> R1–R9 已知真缺口 + busy 状态机攻击、R10–R19 数据流/迁移矩阵攻击、
> R20–R23 并发与性能攻击（**发现并修复 O(n²) 流式显示悬崖**）、
> R24–R33 遗留攻击面逐项坐实、R34–R45 文档与收口、R46–R50 冻结。
> 回归基线：v0.7.9 全量 31 文件 31 OK。终态：34 文件 34 OK 零失败。

---

## R1 — 固定历史接通（第四例死功能）

- **攻击坐实**：`history.pin_history` 生产代码零调用（仅定义 + prune 被动引用）——
  README 宣称的「历史治理：固定重要项(pinned)」用户无法触达，pinned 只在
  保留天数清理时被动生效。继 R3 备份入口、附加约束、render_template 之后第四例。
- **做了什么**：`list_history` 查询补 pinned 列（8→9 列，export_markdown/过滤/渲染
  全链路兼容）；库对话框「固定/取消固定」按钮 + 📌 列表标记。
- **验证**：test_round7_ui 3 用例（翻转落库/未选中提示/9 列导出兼容）。

## R2 — 设置「打开配置目录」按钮

config.json / .bak / promptpop.log / SQLite 都在一个目录，排障常需——备份 tab 一键打开
（os.startfile，失败弹目录路径）。

## R3 — 托盘「关于 PromptPop」

版本号此前只能翻 `__init__.py`。`__version__` 升为运行时唯一来源（0.7.3 → 0.7.10，
历史上一直没跟版本走），托盘关于显示版本 + 配置目录。

## R4 — 设置面板重复打开守卫

托盘/浮窗/气泡多个入口都能开设置——连点时排队叠弹。守卫：`_active_dialog` 已是
「PromptPop 设置」且可见 → 只 raise_ 不叠开。

## R5–R7 — 上述改动回归测试（test_round7_ui.py，7 用例）

## R8 — busy 状态机攻击（坐实 + 修复）

- **攻击坐实**：优化流式进行中打开库加载（或本地整理「应用」）——result_box 被程序化
  覆盖（readOnly 不拦 setPlainText），随后到来的 token 追加在加载内容尾部，
  **实测内容混合**（「库里的输出…流式剩余token」）且历史元数据错位。
- **修复**：`_on_library_load` / `_on_local_tools` busy 时拦截提示「先取消再加载」。
- **穷尽走查 result_box 全部写点**：_on_token/_on_done/_on_failed（worker 自身路径）、
  _on_clear/按钮（busy 禁用）、_on_diff（只读）——R10–R15 逐项确认无第三个漏点。

## R16–R19 — 数据流攻击

- **坏配置 → 真实启动链**：custom_providers=dict、温度/上限/热键/保留天数全坏值 →
  `Config.load() → OverlayWindow(cfg)` 实测构造不崩（固化 adv_dataflow）。
- **模板全链路**：导入 → 编辑 → 同名保存查重 → 导出 → 再导入 merge 去重 ✓。
- **迁移矩阵（R18）**：DEFAULT_CONFIG 31 字段 × 10 坏值 = **310 组合零崩溃**
  （固化进 adv_config 防回归）。

## R20–R23 — 并发与性能攻击（本轮最大发现）

- **R20 并发写**：双线程 × 60 条并发 add_history → 120 条零错误 0.32s ✓。
- **R21 千条性能**：1000 条 list+filter+export 0.01s ✓。
- **R22 性能悬崖（真缺陷）**：**1MB 流式分块显示实测 153 秒**——
  `_on_token` 逐 chunk `moveCursor+insertPlainText` 在长文本下 O(n²)
  （每次插入触发全文重排）。默认 2 万字上限下输出 10 万字级也有数秒~数十秒卡顿。
- **R23 修复**：`_stream_buf` 攒 chunk + 60ms `QTimer` 批量插入（`_flush_stream_buf`），
  insert 次数降两个量级；busy 结束（含失败/取消）先冲缓冲保留已收内容。
  test_stream_buffer.py 4 用例固化（含 1MB <20s 性能守卫断言）。

## R24–R33 — 遗留攻击面逐项坐实（无代码改动，记录结论）

信号重复连接（构造一次无重复）、双实例（QLockFile，离屏无法双进程实测，代码审查）、
SQLite 外部锁（调用点 try + Qt slot 异常隔离）、extra_edit 2000 硬限、连点取消幂等、
hide/show 连发、judge 期间按钮禁用矩阵、quick_optimize busy 拦截——全部有防御。

## R34–R38 — README 同步（版本头/5 条新功能/3 个新测试文件）+ 版本号

`__version__` 与 version_info.py 同步 **0.7.10**（__init__ 的 0.7.3 是历史遗留漂移，
本轮起两处手动同步并注释互指）。

## R39 — 本日志

## R40–R45 — 全量回归与走查

py_compile 全过；全量 run_all 34 文件 34 OK（两次确认，见 R50）。
打包 spec 检查：PromptPop-onefile.spec 引用 version_info.py ✓（exe 未重打包）。

---

## 本轮周期收尾汇总（v0.7.10，R1–R50）

| 轮次 | 主题 | 类型 |
|---|---|---|
| R1 | 固定历史接通（pin 死功能第四例） | 真缺口 |
| R2 | 打开配置目录 | 体验 |
| R3 | 托盘关于（版本单一来源化） | 体验 |
| R4 | 设置重复打开守卫 | 健壮性 |
| R5–R7 | 回归测试 7 用例 | 回归 |
| R8 | busy 时库加载/本地整理拦截（内容混合坐实） | 真缺陷 |
| R9 | R8 回归测试固化 | 回归 |
| R10–R15 | result_box 写点穷尽走查（无第三漏点） | 走查 |
| R16–R19 | 坏配置启动链 + 模板全链路 + 迁移矩阵 310 组合 | 攻击体系 |
| R20–R21 | 并发写/千条性能坐实 | 攻击体系 |
| R22–R23 | **O(n²) 流式显示 153s → 缓冲批量刷新** | 真缺陷/性能 |
| R24–R33 | 遗留攻击面坐实（10 项，零改动） | 攻击体系 |
| R34–R38 | README/版本同步（__version__ 漂移修复） | 文档 |
| R39–R45 | 日志/全量回归/spec 检查 | 收尾 |
| R46–R50 | 全量回归 ×2 + 落大脑 + 冻结 | 收尾 |

- **版本**：`__version__`/version_info.py **0.7.10**。
- **回归**：`run_all.py` **34 文件 34 OK 零失败**（新增 test_round7_ui 10 用例 +
  test_stream_buffer 4 用例 + adv_dataflow 5 用例 + adv_config 扩展 1）。
- **待真机确认**（不谎报）：
  1. 流式缓冲的真实观感（60ms 批量在正常网速下应与逐字无差）。
  2. 全局主题/工具条亮色（v0.7.9 遗留）。
  3. 历届真机项继续有效（划词覆盖率/管理员窗口/provider 分类/导入不重启/弹窗置顶）。
- **已知不做**：价目表分时化、历史分页、IAccessible、迭代版本回退、
  hide 防抖写盘、result_box 超限降级显示（缓冲已解决主要卡顿）。

## 回滚方式
本轮触碰源码 8 个文件（history/library_dialog/settings_dialog/app/__init__/
overlay/version_info/README）+ tests 3 个（run_all/adv_config/test_round7 新建 +
test_stream_buffer 新建 + adv_dataflow 新建），恢复到 v0.7.9 内容并删除 3 个新测试
文件即可；exe 未重打包，桌面产物未动。
