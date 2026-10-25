"""Ollama 可用性探测（GET /api/tags）。依据 Ollama REST 健康检查实践。"""
import json
import time
import urllib.error
import urllib.request

# 探测结果缓存：Ollama 未启动时每次点「优化」都同步等满 timeout 会卡住界面，
# 缓存 N 秒内的结果，避免反复阻塞主线程。
_CACHE = {"url": None, "ok": False, "ts": 0.0}
_CACHE_TTL = 10.0


def _tags_url(base_url):
    b = (base_url or "").rstrip("/")
    if b.endswith("/v1"):
        b = b[:-3]
    return b + "/api/tags"


def is_ollama_up(base_url, timeout=3.0):
    cached = _CACHE
    now = time.monotonic()
    if (cached["url"] == base_url and cached["ok"]
            and (now - cached["ts"]) < _CACHE_TTL):
        return True  # 只缓存「可达」结论；不可达不缓存，保证服务起来后能尽快恢复
    try:
        req = urllib.request.Request(_tags_url(base_url), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok = (r.status == 200)
    except Exception:
        ok = False
    if ok:
        cached.update(url=base_url, ok=True, ts=now)
    return ok


def ollama_models(base_url, timeout=3.0):
    try:
        with urllib.request.urlopen(_tags_url(base_url), timeout=timeout) as r:
            data = json.load(r)
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []
