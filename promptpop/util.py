"""纯函数小工具（可单测）：窗口定位夹取、历史过滤、模板变量。"""
import re

_VAR_RE = re.compile(r"\{\{\s*([\w\u4e00-\u9fa5]+)\s*\}\}")


def clamp_position(x, y, w, h, left, top, right, bottom, margin=8):
    """把 (x,y) 处的 w×h 窗口夹取进屏幕可用区；窗口大于可用区时居中避免溢出。"""
    aw = right - left
    ah = bottom - top
    if w >= aw - 2 * margin:
        nx = left + max(margin, (aw - w) // 2)
    else:
        nx = min(max(x, left + margin), right - w - margin)
    if h >= ah - 2 * margin:
        ny = top + max(margin, (ah - h) // 2)
    else:
        ny = min(max(y, top + margin), bottom - h - margin)
    return nx, ny


def filter_history(rows, query):
    """rows: (id, ts, mode, provider, model, input, output[, tags])。按关键词过滤（含标签）。"""
    if not query:
        return list(rows)
    q = query.lower()
    out = []
    for r in rows:
        fields = (r[2], r[3], r[4], r[5], r[6])
        if len(r) > 7:  # 新版含 tags 列，一并参与搜索
            fields = fields + (r[7],)
        blob = " ".join(str(x) for x in fields).lower()
        if q in blob:
            out.append(r)
    return out


def extract_vars(text):
    """提取 {{var}} 变量名（保序去重）。"""
    seen = []
    for m in _VAR_RE.finditer(text or ""):
        v = m.group(1)
        if v not in seen:
            seen.append(v)
    return seen


def render_template(text, mapping):
    """用 mapping 渲染 {{var}}；未提供的变量原样保留。"""
    def repl(m):
        return str(mapping[m.group(1)]) if m.group(1) in mapping else m.group(0)
    return _VAR_RE.sub(repl, text or "")


def mask_secret(s):
    """脱敏：仅露头 3 + 尾 4，避免 Key 出现在日志/报错里。"""
    s = str(s or "")
    n = len(s)
    if n == 0:
        return ""
    if n <= 8:
        return "*" * n
    return s[:3] + "..." + s[-4:]


def validate_temperature(v):
    """返回 [0,2] 的 float，非法返回 None。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f < 0 or f > 2:
        return None
    return f


def safe_int(v, default=0):
    """配置读取的整数安全转换：坏值/None 返回 default（不崩主路径）。

    背景：配置文件可能被手改成坏值（如 "abc"）——裸 int() 会让取词/优化
    主路径直接抛 ValueError（对抗性测试 adv_config 坐实后统一替换）。
    """
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def safe_float(v, default=0.0):
    """配置读取的浮点安全转换：坏值/None 返回 default。

    同时修复原 `float(x or d)` 写法——0.0 是 falsy，会把用户合法设置的
    0 温度（greedy 解码）悄悄变成默认 0.3。
    """
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def validate_base_url(url):
    u = (url or "").strip()
    return u.startswith("http://") or u.startswith("https://")


def scrub_secret(text, secret):
    """把文本中出现的 secret 替换为脱敏串，防 Key 漏进报错/日志。"""
    if not text or not secret:
        return text
    return str(text).replace(secret, mask_secret(secret))


# ---------- 热键：校验 / 显示 ----------
_MOD_MAP = {"ctrl": "<ctrl>", "control": "<ctrl>", "shift": "<shift>",
            "alt": "<alt>", "win": "<cmd>", "cmd": "<cmd>", "super": "<cmd>"}
_KEY_MAP = {"space": "<space>", "enter": "<enter>", "return": "<enter>",
            "esc": "<esc>", "escape": "<esc>", "tab": "<tab>",
            "up": "<up>", "down": "<down>", "left": "<left>", "right": "<right>",
            "backspace": "<backspace>", "delete": "<delete>", "home": "<home>",
            "end": "<end>", "pageup": "<pageup>", "pagedown": "<pagedown>"}


def _norm_token(t):
    t = (t or "").strip().lower()
    if not t:
        return None
    if t in _MOD_MAP:
        return _MOD_MAP[t]
    if t in _KEY_MAP:
        return _KEY_MAP[t]
    # 仅 ASCII 单字可作键名：中文/全角单字 isalnum() 为真，曾把「ctrl+加」
    # 接受成合法热键并注册出无效组合
    if len(t) == 1 and t.isascii() and t.isalnum():
        return t
    if re.fullmatch(r"f([1-9]|1[0-2])", t):   # F1..F12
        return "<%s>" % t
    return None


def validate_hotkey(s):
    """把常见写法（Ctrl+Shift+Space / ctrl+shift+space）规范为内部格式；
    非法返回 None。内部格式形如 <ctrl>+<shift>+<space>。

    **必须恰好满足：至少 1 个修饰键 + 至少 1 个主键。**
    这条与 hotkey.parse_combo 的规则严格对齐——否则会出现「输入框旁提示可用、
    保存后注册失败」（例如只有修饰键的 Ctrl+Shift、或没有修饰键的 A+B）。
    """
    if not s or not str(s).strip():
        return None
    parts = [p for p in str(s).replace(" ", "").split("+") if p]
    if len(parts) < 2:
        return None
    norm = [_norm_token(p) for p in parts]
    if any(n is None for n in norm):
        return None
    mods = set(_MOD_MAP.values())
    has_mod = any(n in mods for n in norm)
    has_key = any(n not in mods for n in norm)
    if not (has_mod and has_key):
        return None
    return "+".join(norm)


def format_hotkey(s):
    """内部热键 → 可读显示：<ctrl>+<shift>+space → Ctrl+Shift+Space。"""
    if not s:
        return ""
    out = []
    for p in str(s).split("+"):
        p = p.strip().strip("<>").lower()
        out.append({
            "ctrl": "Ctrl", "control": "Ctrl", "shift": "Shift", "alt": "Alt",
            "cmd": "Win", "space": "Space", "enter": "Enter", "esc": "Esc",
        }.get(p, p.capitalize()))
    return "+".join(out)


# Windows 系统占用的 Win+ 组合：即使 RegisterHotKey/GlobalHotKeys 注册成功也收不到，
# 且会抢占系统快捷键（锁屏/运行/资源管理器等）。保存前必须拦截。
_RESERVED_WIN = {
    "<cmd>+l", "<cmd>+u", "<cmd>+r", "<cmd>+e", "<cmd>+d", "<cmd>+m",
    "<cmd>+space", "<cmd>+tab", "<cmd>+p", "<cmd>+x", "<cmd>+i", "<cmd>+a",
    "<cmd>+s", "<cmd>+v", "<cmd>+k", "<cmd>+h", "<cmd>+g", "<cmd>+<printscreen>",
}


def check_hotkey_risk(combo):
    """热键风险评估（纯函数，可单测）。

    返回 (block, warning)：
    - block=True  → 系统保留/非法，应阻止保存（如 Win+L 锁屏）；
    - warning 非空 → 非阻断风险提示，可放行但应告知用户（如含 Space 易冲突）。
    combo 兼容两种键名形态：validate_hotkey 产出的 <space> 形态与
    pynput 规范的裸 space 形态——保留表以两种形态混存，双查避免
    Win+Space/Win+Tab（validate 形态）失防。
    """
    if not combo:
        return True, "热键为空"
    tokens = [t.strip().lower() for t in str(combo).split("+")]

    def _bare(s):
        return s.lower().replace("<", "").replace(">", "")

    # 保留表历史形态混杂（<cmd>+l 与 <cmd>+space：<cmd> 带尖、键裸），而
    # validate_hotkey 产出 <cmd>+<space> 全带尖、pynput 规范为 cmd+l 全裸——
    # 统一去尖比较，三种形态都能命中（此前 <cmd>+<space>/<tab> 失防）
    reserved_bare = {_bare(x) for x in _RESERVED_WIN}
    if "<cmd>" in tokens and _bare(combo) in reserved_bare:
        return True, ("该 Win+ 组合被 Windows 系统占用（如 Win+L 锁屏），无法生效，请换一个组合")
    if "<space>" in tokens or "space" in tokens:
        return False, ("含 Space 的组合（如 Ctrl+Shift+Space）易与中文输入法或编辑器冲突；"
                      "若发现唤起失灵可改换为非 Space 组合")
    return False, ""


def should_guide_first_run(cfg_data, needs_key, has_key):
    """是否应做「首次使用」引导（纯函数，可单测）。

    条件：①没跑过引导（``first_run_done`` 未置）②当前提供商需要 Key ③确实没配 Key。
    本地 Ollama（needs_key=False）不需要引导；已配 Key 的老用户也不会被打扰。
    """
    if (cfg_data or {}).get("first_run_done"):
        return False
    return bool(needs_key) and not bool(has_key)


# ---------- 成本估算 ----------
# 注意：下表为 2025 年单一价（USD/百万 tokens）。DeepSeek 2026 年起改为峰谷分时
# + 缓存命中分级定价（官方 api-docs.deepseek.com/quick_start/pricing），固定二元组
# 已无法精确表达——本表仅供 ≈ 量级参考，未知模型不显示成本。
PRICE_TABLE = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-3-5-sonnet": (3.00, 15.00),
}


def estimate_cost(model, usage, prices=None):
    """按 token 用量估算成本（USD）；未知模型或空用量返回 None。"""
    prices = prices or PRICE_TABLE
    if not usage or not isinstance(usage, dict):
        return None
    key = (model or "").strip().lower()
    if key not in prices:
        return None
    pin, pout = prices[key]
    pt = safe_float(usage.get("prompt_tokens"), 0)
    ct = safe_float(usage.get("completion_tokens"), 0)
    return (pt / 1_000_000.0) * pin + (ct / 1_000_000.0) * pout


# ---------- 差异视图 ----------
def diff_lines(old_text, new_text, meta_label=("原文", "优化")):
    """对比两段文本（按行），返回统一 diff 行列表（纯函数，便于单测）。
    行首：'  '=相同，'- '=仅原文，'+ '=仅优化。"""
    import difflib
    a = (old_text or "").splitlines()
    b = (new_text or "").splitlines()
    sm = difflib.SequenceMatcher(None, a, b)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in a[i1:i2]:
                out.append("  " + line)
        elif tag == "delete":
            for line in a[i1:i2]:
                out.append("- " + line)
        elif tag == "insert":
            for line in b[j1:j2]:
                out.append("+ " + line)
        elif tag == "replace":
            for line in a[i1:i2]:
                out.append("- " + line)
            for line in b[j1:j2]:
                out.append("+ " + line)
    return out


# ---------- 浮窗快捷键解析（便于单测） ----------
def resolve_overlay_shortcut(ctrl, shift, key):
    """根据修饰键与主键返回动作名；无匹配返回 ''。"""
    if ctrl and shift:
        if key in ("c", "C"):
            return "copy_all"
    if ctrl and not shift:
        if key in ("i", "I"):
            return "insert"
        if key in ("r", "R"):
            return "replace"
        if key in ("d", "D"):
            return "diff"
        if key in ("return", "enter"):
            return "optimize"
    if key in ("escape", "esc"):
        return "cancel"
    return ""


def format_char_count(n, mx):
    """输入框实时字数提示：返回 (显示文本, 颜色类别)。

    颜色类别 ∈ error / warn / info，供 UI 把超限标红、逼近上限标黄。
    warn 仅覆盖「90%<占比<100%」区间——恰好等于上限（提交仍允许）按 info 处理，
    与 _on_optimize 的 `len(text) > mx` 严格拦截保持一致。
    纯函数，可单测；UI 只负责把它渲染到标签上。
    """
    if mx > 0 and n > mx:
        return ("超限 %d / %d 字" % (n, mx), "error")
    if mx > 0 and mx * 0.9 < n < mx:
        return ("%d / %d 字" % (n, mx), "warn")
    extra = ("（上限 %d）" % mx) if mx > 0 else ""
    return ("%d 字%s" % (n, extra), "info")
