"""配置持久化：JSON + 版本号 + 迁移（升级不丢配置、自动补默认/去下线键）。

历史/模板入 SQLite（history.py）。
"""
import json
import os
from pathlib import Path

APP_NAME = "PromptPop"
CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "provider": "deepseek",                 # deepseek | openai | ollama
    "model": "deepseek-chat",
    "mode": "user",                          # user | system
    "api_keys": {"deepseek": "", "openai": "", "ollama": ""},
    "ollama_base_url": "http://localhost:11434/v1",
    "proxy": "",                             # LLM 代理 http://host:port（校园网国际出站用）
    "hotkey": "<ctrl>+<shift>+<space>",   # 规范格式（与 util.validate_hotkey 输出一致）
    "theme": "dark",                         # dark | light
    "temperature": 0.3,
    "request_timeout": 60.0,                 # LLM 读取超时（秒，流式应较大）
    "connect_timeout": 10.0,                 # LLM 连接超时（秒）
    "max_retries": 2,                        # 瞬时错误重试次数（仅连接阶段安全重试）
    "max_input_chars": 20000,                 # 单条输入上限；0 = 不限制（防爆单/上下文溢出）
    "meta_variant": "standard",              # standard | concise | strict
    "exclude_cursor_detect": [],             # 跳过光标降智的程序（自定义光标，如 acrobat）
    "clipboard_delay_read": [],              # 多次写剪贴板的程序（如 acrobat）
    "clipboard_delay_default": 0.12,          # 取词读剪贴板默认等待（秒，主线程阻塞，勿过大）
    "clipboard_delay_slow": 0.28,             # 上述程序对应的更长等待
    "selection_toolbar": True,               # 划词自动弹工具条
    "selection_exclude_programs": ["explorer", "dopusrt", "dllhost"],
    # 这些程序里「拖拽」通常是移动文件/窗口而非选文字，取词会误触发剪贴板抖动/误弹，跳过
    "autostart": False,                      # 开机自启
    "debug_log": False,                      # 写调试日志到文件
    "history_retention_days": 0,             # >0 时清理该天数前的非固定历史
    "window_width": 0,                       # 浮窗尺寸记忆（0 = 用默认大小）
    "window_height": 0,
    "custom_meta_user": "",                  # 空 = 用默认模板
    "custom_meta_system": "",
    "custom_providers": [],                   # 用户自定义 OpenAI 兼容端点列表
    "notify_on_done": True,                   # 生成完成后弹托盘气泡通知（不必盯着窗口）
    "first_run_done": False,                  # 首次运行引导是否已展示（装一次只引导一次）
}


def reset_to_defaults(data=None, keep=("api_keys", "custom_providers")):
    """把配置重置为默认值，但保留「用户数据」类字段（自定义端点、旧 api_keys）。

    纯函数：返回新 dict，不落盘；供设置面板「恢复默认」使用，便于单测。
    不保留历史/模板（它们在 SQLite 里，与本函数无关）。
    """
    out = json.loads(json.dumps(DEFAULT_CONFIG))
    src = data if isinstance(data, dict) else {}
    for k in keep:
        if k in src and k in out:
            try:
                out[k] = json.loads(json.dumps(src[k]))
            except Exception:
                pass
    return out


def migrate(data):
    """迁移任意旧配置到当前 schema：补默认、去下线键、置版本号。纯函数，可单测/幂等。"""
    out = json.loads(json.dumps(DEFAULT_CONFIG))
    if isinstance(data, dict):
        for k, v in data.items():
            if k not in out:
                continue  # 丢弃已下线键
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
    out["config_version"] = CONFIG_VERSION
    return out


def config_dir() -> Path:
    override = os.environ.get("PROMPTPOP_CONFIG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_NAME
    return Path.home() / ".config" / "promptpop"


def config_path() -> Path:
    return config_dir() / "config.json"


class Config:
    def __init__(self, data=None):
        self.data = migrate(data)

    @classmethod
    def load(cls):
        p = config_path()
        raw = None
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                raw = None  # 损坏：下面尝试从 .bak 恢复，而非静默重置全部配置
        if raw is None:
            bak = p.with_suffix(".json.bak")
            if bak.exists():
                try:
                    raw = json.loads(bak.read_text(encoding="utf-8"))
                    print("[config] 主配置损坏，已从备份恢复：%s" % bak)
                except Exception:
                    raw = {}
        return cls(raw or {})

    def save(self):
        self.data["config_version"] = CONFIG_VERSION
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        # 保存前先备份上一份，防写坏丢失配置
        if p.exists():
            try:
                p.replace(p.with_suffix(".json.bak"))
            except Exception:
                pass
        # 原子写：先写临时文件再替换，避免写一半进程被杀导致配置半截损坏
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(p)

    def export_to(self, path):
        """导出配置到任意路径（便于备份/迁移）。"""
        Path(path).write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_from(self, path):
        """从任意路径导入配置（经 migrate 安全合并到当前 schema）。

        顶层不是 JSON 对象（如 list/字符串）时抛 ValueError：静默 migrate 成
        默认配置会让用户原配置在下次 save 时被整体覆盖，等于导入坏文件毁配置。"""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("配置文件格式无效：顶层应为 JSON 对象（{...}）")
        self.data = migrate(raw)
        return self.data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
