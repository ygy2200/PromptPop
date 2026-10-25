# PromptPop 优化迭代日志 · 第八轮 30 轮循环（v0.7.11）

> 执行：zcode，2026-10-25。承接第七轮（v0.7.10 已发布 GitHub+桌面）。
> 本轮主题：**exe 真机验证还债**（历轮"待真机确认"项）+ keyring 特性真相 + 新攻击面 + 发布自动化。
> 终态：全量 34 文件 34 OK；v0.7.11 发布。

---

## R1–R2 — exe 真机冒烟（历轮欠账首次偿还）

- 隔离配置目录启动桌面 exe：进程存活、config.json 31 字段正确初始化、
  provider/model/hotkey/first_run_done 全部正确、**无 crash.log** ✓
- 双启动单实例：锁生效，第二实例弹「已在运行中」模态框滞留等待点击
  （预期行为；真机观察到的细节：无人值守时第二实例进程会挂着直到点击）。
- 清理：taskkill 后零残留。

## R3 — onefolder spec 同步修复（自己上一轮的改 A 漏 B）

上轮只修了 onefile spec 的 excludes/upx，`PromptPop.spec` 仍是 `excludes=[]`+`upx=True`×2
——同步修复（excludes 15 库 + 三处 upx=False）。

## R4–R5 — warn 文件分析 + keyring 特性真相（本轮最大发现）

- R4 分析 `warn-PromptPop-onefile.txt`（134 missing，多为跨平台噪音），锁定唯一关键项：
  **keyring 标记 missing**。
- R5 真机迁移验证：给 exe 喂明文 Key → 启动 → **Key 未迁移（降级路径）**——
  exe 内 keyring 不可用。
- 根因深挖：**源码环境根本没装 keyring**（`import keyring` → ModuleNotFoundError）。
  它在 requirements.txt 里声明了三周但从未安装。结论：
  **「API Key 存系统钥匙串」自 v0.7.2 宣称以来从未真正工作过**——
  历轮 test_rounds 的 headless skip 被误读为「环境限制」，实为「根本没装」。

## R6–R8 — 补装 keyring + 重打包

- `pip install --user keyring`（requirements 既有声明；直连 pypi 超时，走代理 7890）。
- 源码环境：WinVaultKeyring 真后端 ✓，set/get/delete 全链路 ✓，
  test_rounds 从 skip 转为真验证通过。
- 重打包 dist_v711。

## R15 — 新 exe keyring 迁移真机验证（特性首次真工作）

- v0.7.11 exe 喂明文 Key → 启动 → **Key 成功迁入 Windows 凭据管理器** ✓
- 测试残留凭据已清理（secrets.set_key 置空）。

## R9 — 设置半保存攻击：坐实无恙

坏温度 + 填新 Key → 保存被拦，Key 未泄漏入钥匙串（校验前置防御有效）。

## R10–R13 — providers/resolve 攻击矩阵：抓到新崩溃并修复

- **R11 坐实**：api_keys 被手改成 scalar/list/int → `resolve` 与
  `secrets.resolve_api_key` 抛 AttributeError——`_run_worker` 每次优化都经过。
- **R12 修复**：`providers._global_key` + `secrets.resolve_api_key` 统一 isinstance 防御；
  6 种坏类型全矩阵过 + 正常路径无回归。
- **R13 固化**进 adv_config.py。

## R14 — quick_optimize busy 语义：确认可接受

工具条一键直达在生成中点击 → `_on_optimize` → `_run_worker` 守卫提示
「正在生成中…要换内容请先点取消」（浮窗已 show，状态栏可见）——设计如此，不改。

## R16 — 发布一条龙 release.py（固化惯例）

`python release.py 0.7.11` = 全量回归(零失败才继续) → 打包 → exe 版本元信息校验
→ 桌面部署(自动备份旧件) → git commit+push(代理) → Release+exe 上传(git credential)。
本轮就踩到它要防的坑：先打包后改版本号导致 exe 元信息还是 0.7.10.0（R18 重打）。

## R17–R18 — 版本 0.7.11 + README + 重打包

## R19–R30 — 全量回归 + 发布 + 落大脑

---

## 汇总（v0.7.11，R1–R30）

| 轮次 | 主题 | 类型 |
|---|---|---|
| R1–R2 | exe 真机冒烟（启动/配置初始化/单实例） | 真机验证 |
| R3 | onefolder spec 同步修复 | 改A漏B |
| R4–R5 | keyring 特性真相（从未工作过） | 重大发现 |
| R6–R8 | 补装 keyring + 源码链路验证 + 重打包 | 修复 |
| R15 | 新 exe keyring 迁移真机通过 | 真机验证 |
| R9 | 半保存攻击坐实无恙 | 攻击 |
| R10–R13 | api_keys 坏类型崩溃修复 + 固化 | 真缺陷 |
| R14 | quick_optimize busy 语义确认 | 走查 |
| R16 | release.py 一条龙 | 工程化 |
| R17–R30 | 版本/回归/发布/记录 | 收尾 |

- **版本**：0.7.11.0；**回归**：34 文件 34 OK。
- **待真机确认**：划词取词覆盖率、管理员窗口粘贴、代理下 Ollama、全局主题观感
  （历届遗留，exe 已部署可随时人工验证）。
- **环境事实**：pypi 直连不通需代理；keyring 已装（--user）。

## 回滚
源码 5 文件（providers/secrets/两个 spec/版本文件+README）恢复 v0.7.10；
`pip uninstall keyring` 可还原环境；桌面/GitHub Release 按网页端可撤。
