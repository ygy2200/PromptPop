"""优化结果后处理：去 markdown 围栏、去常见英文赘述前缀、去首尾空白。

依据：kerb clean_llm_output / llm-json-repair strip_fences / llm-markdown-sanitizer。
保守起见仅去英文客套前缀，避免误伤中文提示词正文。
"""
import re

_FENCE_RE = re.compile(r"^```[ \t]*[\w-]*[ \t]*\n(?P<body>.*?)\n?```[ \t]*$", re.DOTALL)
_PREFIXES = [
    r"^sure[,!]?\s+here(?:'s| is)\s+(?:the\s+)?",
    r"^here(?:'s| is)\s+(?:the\s+)?",
    r"^(?:ok|okay)[,!\s]+",
]


def strip_fences(text: str) -> str:
    t = (text or "").strip()
    m = _FENCE_RE.match(t)
    if m:
        return m.group("body").strip()
    for fence in ("```", "~~~"):
        if t.startswith(fence):
            rest = t[len(fence):].lstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-\t ")
            t = rest.split("\n", 1)[1] if "\n" in rest else rest
            break
    for fence in ("```", "~~~"):
        s = t.rstrip()
        if s.endswith(fence):
            t = s[: -len(fence)]
            break
    return t.strip()


def strip_leading_prefixes(text: str) -> str:
    t = (text or "").lstrip()
    changed = True
    while changed:
        changed = False
        for p in _PREFIXES:
            new = re.sub(p, "", t, flags=re.IGNORECASE)
            if new != t:
                t = new.lstrip()
                changed = True
    return t


def postprocess_output(text: str) -> str:
    if not text:
        return text
    return strip_leading_prefixes(strip_fences(text)).strip()
