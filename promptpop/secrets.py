"""API Key 安全存储：优先 keyring（Windows Credential Manager / macOS Keychain），
无 keyring 或无后端时回退 config 明文；启动时把 config 旧明文迁移进 keyring 并清空。

依据：keyring 官方用法 + CLI 凭证存储最佳实践（tokenstore 模式）。
注意：keyring 为**惰性加载**（首次用到才 import）——
①顶层硬 import 会让未安装 keyring 的全新环境在启动时直接 ModuleNotFoundError 崩溃；
②keyring 自身导入约 275ms，属启动关键路径上最大的单项开销，而多数启动
（config 里已无明文 Key 可迁移）根本用不到它。
"""
_keyring = None
_keyring_loaded = False


def _kr():
    """按需加载并缓存 keyring；未安装/导入失败返回 None（调用方走降级分支）。

    同时可供测试判断「本环境有无 keyring 后端」。
    """
    global _keyring, _keyring_loaded
    if not _keyring_loaded:
        _keyring_loaded = True
        try:
            import keyring as _k
        except Exception:  # noqa: BLE001 —— 未安装/导入失败均降级
            _k = None
        _keyring = _k
    return _keyring


SERVICE = "PromptPop"


def backend_available():
    kr = _kr()
    if kr is None:
        return False
    try:
        from keyring.backends import fail
        return not isinstance(kr.get_keyring(), fail.Keyring)
    except Exception:
        return False


def get_key(provider):
    kr = _kr()
    if kr is None:
        return ""
    try:
        return kr.get_password(SERVICE, provider) or ""
    except Exception:
        return ""


def set_key(provider, value):
    """返回是否成功。无 keyring/后端故障时返回 False（调用方应提示用户）。"""
    kr = _kr()
    if kr is None or not backend_available():
        return False
    try:
        if value:
            kr.set_password(SERVICE, provider, value)
        else:
            try:
                kr.delete_password(SERVICE, provider)
            except Exception:
                # 「删条目」失败不能报成功（否则调用方以为 Key 已清空，实际还在）
                return False
        return True
    except Exception:
        return False


def has_key(provider):
    return bool(get_key(provider))


def resolve_api_key(cfg_data, provider):
    """keyring 优先，回退 config 明文（兼容未迁移/无 keyring 环境）。"""
    k = get_key(provider)
    if k:
        return k
    return (cfg_data.get("api_keys", {}) or {}).get(provider, "")


def migrate_plaintext_to_keyring(cfg):
    """把 config 里的明文 key 迁进 keyring 并清空 config。返回迁移数量。"""
    if not backend_available():
        return 0
    keys = cfg.get("api_keys", {}) or {}
    moved = 0
    for prov, val in list(keys.items()):
        if val and set_key(prov, val):
            keys[prov] = ""
            moved += 1
    if moved:
        cfg.set("api_keys", keys)
        cfg.save()
    return moved
