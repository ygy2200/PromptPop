"""本地文本整理动作：不需要 API Key、不联网、零成本。

价值：没配 Key 的用户（或想先手动清理文本时）也能用上 PromptPop；
也便于在调用 LLM 前先做一步确定性清理，减少 token 浪费。

全部为纯函数，可单测。
"""
import json
import re

_URL_RE = re.compile(r"https?://[^\s<>\"'）】>]+", re.I)
# 末尾可能粘上的标点（半角 + 全角），提取后剥掉
_URL_TRAIL = ".,;:!?)\u3002\uff0c\uff1b\uff1a\uff01\uff09\u3011\u300b\"'"


def clean_ws(text):
    """清理空白：统一换行、去行尾空白、压缩 3+ 连续空行为单个空行、去首尾空行。"""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip("\n")


def to_bullets(text):
    """非空行转为 Markdown 无序列表（已是列表项的不重复加）。"""
    out = []
    for line in clean_ws(text).split("\n"):
        s = line.strip()
        if not s:
            out.append("")
        elif re.match(r"^([-*+]|\d+[.)])\s+", s):
            out.append(s)          # 已是列表项，保持原样
        else:
            out.append("- " + s)
    return "\n".join(out)


def to_numbered(text):
    """非空行转为有序列表（1. 2. 3. …）。"""
    out, n = [], 0
    for line in clean_ws(text).split("\n"):
        if line.strip():
            n += 1
            s = line.strip()
            s = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)   # 去掉原有列表符号
            out.append("%d. %s" % (n, s))
        else:
            out.append("")
    return "\n".join(out).strip("\n")


def strip_code_fence(text):
    """去掉包裹全文的 ``` 代码围栏（模型输出常见，便于直接使用）。"""
    t = (text or "").strip()
    m = re.match(r"^```[a-zA-Z0-9_+-]*\s*\n(.*?)\n?```\s*$", t, re.S)
    if m:
        return m.group(1).strip()
    return t


def pretty_json(text):
    """JSON 美化缩进；不是合法 JSON 则原文返回（并标记）。"""
    t = strip_code_fence(text or "").strip()
    if not t:
        return text or ""
    try:
        obj = json.loads(t)
    except Exception:
        return t
    return json.dumps(obj, ensure_ascii=False, indent=2)


def dedupe_lines(text):
    """按行去重（保序，忽略首尾空白差异）；空行保留结构但不参与去重。"""
    seen = set()
    out = []
    for line in (text or "").split("\n"):
        key = line.strip()
        if not key:
            out.append(line)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return "\n".join(out)


def extract_urls(text):
    """抽出所有 URL，每行一个；没有则返回空串。"""
    urls = []
    for u in _URL_RE.findall(text or ""):
        u = u.rstrip(_URL_TRAIL)
        if u and u not in urls:
            urls.append(u)
    return "\n".join(urls)


_ZH_PUNCT = {
    "，": ",", "。": ".", "！": "!", "？": "?", "；": ";", "：": ":",
    "“": '"', "”": '"', "‘": "'", "’": "'", "（": "(", "）": ")",
}
_ZH_TRANS = str.maketrans(_ZH_PUNCT)


def to_english_punct(text):
    """中文全角标点转英文半角标点（写给英文 LLM 的 prompt 前常需一步）。

    覆盖 ，。！？；：“”‘’（）——把中文标点归一为 ASCII，减少英文模型
    的 token 化异常与标点歧义。已是半角的文本不受影响。
    """
    return (text or "").translate(_ZH_TRANS)


def remove_blank_lines(text):
    """删除所有空行（含仅空白的行），保留非空行；与 clean_ws 不同（后者保留单空行分隔）。

    适合把多段零散文本压成连续块（如批量贴进单字段）。
    """
    return "\n".join(line for line in (text or "").split("\n") if line.strip())


def strip_urls(text):
    """删除所有 URL（extract_urls 的反操作）：清理正文里的链接（脱敏 / 精简）。

    去除 URL 后会把残留的多余连续空格压成单个，但不动首尾与正常间距。
    """
    t = _URL_RE.sub("", text or "")
    return re.sub(r" {2,}", " ", t)


# 名称 → (函数, 说明)
ACTIONS = {
    "clean_ws": (clean_ws, "清理空白（行尾/多余空行/换行符）"),
    "to_bullets": (to_bullets, "转为无序列表 (- )"),
    "to_numbered": (to_numbered, "转为有序列表 (1. 2. 3.)"),
    "strip_code_fence": (strip_code_fence, "去掉 ``` 代码围栏"),
    "pretty_json": (pretty_json, "JSON 美化缩进"),
    "dedupe_lines": (dedupe_lines, "按行去重（保序）"),
    "extract_urls": (extract_urls, "提取所有 URL"),
    "to_english_punct": (to_english_punct, "中文标点转英文标点"),
    "remove_blank_lines": (remove_blank_lines, "删除所有空行"),
    "strip_urls": (strip_urls, "删除所有 URL"),
}


def names():
    return list(ACTIONS.keys())


def apply(name, text):
    """执行指定本地动作，返回处理结果。未知动作原文返回。"""
    fn = ACTIONS.get(name, (None,))[0]
    if fn is None:
        return text or ""
    return fn(text or "")
