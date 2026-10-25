"""Provider 预设。统一走 OpenAI 兼容协议（openai SDK + base_url + key），
DeepSeek / OpenAI / Ollama 三家用同一套调用。"""

PROVIDERS = {
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com",
                 "default_model": "deepseek-chat", "needs_key": True},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1",
               "default_model": "gpt-4o-mini", "needs_key": True},
    "ollama": {"label": "Ollama 本地", "base_url": "http://localhost:11434/v1",
               "default_model": "qwen2.5:7b", "needs_key": False},
}


def _iter_custom(cfg_data: dict):
    """安全迭代自定义端点：custom_providers 被手改成非 list（或条目非 dict）时
    返回空——该字段在 OverlayWindow 构造路径上，崩了等于启动即崩。"""
    lst = (cfg_data or {}).get("custom_providers")
    if not isinstance(lst, list):
        return []
    return [c for c in lst if isinstance(c, dict)]


def get_all_providers(cfg_data: dict):
    """内置 + 自定义端点合并；自定义端点来自 config.custom_providers 列表。"""
    out = dict(PROVIDERS)
    for c in _iter_custom(cfg_data):
        pid = (c.get("id") or c.get("name") or "").strip()
        if not pid:
            continue
        out[pid] = {
            "label": c.get("label") or c.get("name") or pid,
            "base_url": (c.get("base_url") or "").rstrip("/"),
            "default_model": c.get("default_model", "") or "",
            "needs_key": bool(c.get("needs_key", True)),
            "api_key": c.get("api_key", "") or "",
            "custom": True,
        }
    return out


def add_custom_provider(cfg_data: dict, name: str, base_url: str, model: str,
                        api_key: str = "", needs_key: bool = True):
    """往 config 的 custom_providers 追加/更新一个自定义端点，返回其 id。"""
    src = (cfg_data.get("custom_providers") or [])
    lst = [c for c in src if isinstance(c, dict)] if isinstance(src, list) else []
    pid = name.strip()
    entry = {"id": pid, "label": name.strip(), "base_url": base_url.rstrip("/"),
             "default_model": model.strip(), "needs_key": bool(needs_key)}
    if api_key:
        entry["api_key"] = api_key  # 明文存于本地配置（自定义端点多为自建/网关）
    # 同名则更新，否则追加
    for i, c in enumerate(lst):
        if (c.get("id") or c.get("name")) == pid:
            lst[i] = entry
            cfg_data["custom_providers"] = lst
            return pid
    lst.append(entry)
    cfg_data["custom_providers"] = lst
    return pid


def remove_custom_provider(cfg_data: dict, pid: str):
    src = (cfg_data.get("custom_providers") or [])
    lst = [c for c in src if isinstance(c, dict)] if isinstance(src, list) else []
    cfg_data["custom_providers"] = [
        c for c in lst if (c.get("id") or c.get("name")) != pid]


def resolve(provider_id: str, cfg_data: dict):
    """返回 (base_url, api_key, model, needs_key)。支持自定义端点。"""
    p = get_all_providers(cfg_data).get(provider_id, PROVIDERS["deepseek"])
    if p.get("custom"):
        base_url = p["base_url"]
        # 自定义端点的 Key 优先取专属字段，其次取全局 api_keys（便于复用钥匙串）
        api_key = (p.get("api_key")
                   or (cfg_data.get("api_keys", {}) or {}).get(provider_id, ""))
        model = cfg_data.get("model") or p["default_model"]
        return base_url, api_key, model, p["needs_key"]
    if provider_id == "ollama":
        base_url = cfg_data.get("ollama_base_url") or p["base_url"]
        api_key = "ollama"  # 本地服务忽略；SDK 要求非空
    else:
        base_url = p["base_url"]
        api_key = (cfg_data.get("api_keys", {}) or {}).get(provider_id, "")
    model = cfg_data.get("model") or p["default_model"]
    return base_url, api_key, model, p["needs_key"]
