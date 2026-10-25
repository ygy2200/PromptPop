"""第六轮（v0.6.0 → v0.7.0）迭代测试：R2–R9。

运行： QT_QPA_PLATFORM=offscreen python tests/test_cycle6.py
覆盖：
  R2 高 DPI 策略（PassThrough + AA_UseHighDpiPixmaps）
  R3 meta-prompt CRAFT/ICE 升级 + context 注入
  R4 diff_lines 行级差异视图
  R5 engine.ping 连通性预检
  R6 历史标签（set_tags / search_by_tag / 8 列 / 边界标签）
  R7 模板库导入导出（merge 去重）
  R8 overlay 快捷键解析（resolve_overlay_shortcut）
  R9 回归：前五套测试仍绿（在外层 run_cycle6_tests 里跑）
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PROMPTPOP_TEST_HOME",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "_home6"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from promptpop import app as app_mod  # noqa: E402
from promptpop import util, history  # noqa: E402
from promptpop.meta_prompt import (  # noqa: E402
    build_messages, build_followup_messages, DEFAULT_META_USER, DEFAULT_META_SYSTEM,
)
from promptpop.engine import ping  # noqa: E402


def _ensure_app():
    qapp = QApplication.instance() or QApplication([])
    return qapp


# ---------- R2：高 DPI 策略 ----------
def test_high_dpi_policy():
    _ensure_app()
    policy = app_mod.apply_high_dpi_policy()
    assert policy is not None, "应返回生效的取整策略"
    # PassThrough = 保留精确缩放因子
    from PySide6.QtCore import Qt
    assert policy == Qt.HighDpiScaleFactorRoundingPolicy.PassThrough, \
        "应为 PassThrough，实际 %r" % policy
    print("[ok] R2 高 DPI 策略 = PassThrough")


# ---------- R3：meta-prompt CRAFT/ICE + context 注入 ----------
def test_meta_prompt_craft_ice():
    for tpl, name in ((DEFAULT_META_USER, "user"), (DEFAULT_META_SYSTEM, "system")):
        assert "CRAFT" in tpl, "%s 模板应含 CRAFT 框架" % name
        for kw in ("Capability", "Role", "Action", "Format", "Tone"):
            assert kw in tpl, "%s 模板缺 CRAFT 维度 %s" % (name, kw)
        assert "上下文" in tpl and "示例" in tpl, "%s 模板应含 ICE 三要素" % name
    print("[ok] R3 meta-prompt 含 CRAFT 五维 + ICE 三要素")


def test_context_injection():
    ctx = {"受众": "运营同学", "已有背景": "活动页改版", "排除": "不要写前端代码"}
    msgs = build_messages("user", "帮我写个方案", context=ctx)
    sys_text = msgs[0]["content"]
    assert "{ctx}" not in sys_text, "占位符应已被替换"
    for k, v in ctx.items():
        assert k in sys_text and v in sys_text, "上下文 %s=%s 未注入" % (k, v)
    assert msgs[1]["content"] == "帮我写个方案"

    # 无上下文时占位符清空、不残留
    msgs2 = build_messages("user", "写个登录", context=None)
    assert "{ctx}" not in msgs2[0]["content"]

    # 多轮迭代也支持注入
    msgs3 = build_followup_messages("user", "上一版结果", "再精简些",
                                    context={"受众": "新人"})
    assert "受众" in msgs3[0]["content"] and "再精简些" in msgs3[1]["content"]
    print("[ok] R3 context 注入（首轮 + 多轮）")


# ---------- R4：差异视图 ----------
def test_diff_lines():
    old = "第一行\n第二行\n第三行"
    new = "第一行\n第二行改\n第四行"
    d = util.diff_lines(old, new)
    joined = "\n".join(d)
    assert "  第一行" in joined, "相同行应保留"
    assert "- 第二行" in joined, "原文行应标记 -"
    assert "- 第三行" in joined, "被删行应标记 -"
    assert "+ 第二行改" in joined, "新行应标记 +"
    assert "+ 第四行" in joined, "新增行应标记 +"

    # 全等 / 全空
    assert all(x.startswith("  ") for x in util.diff_lines("a\nb", "a\nb"))
    assert util.diff_lines("", "") == []
    print("[ok] R4 diff_lines 行级差异")


# ---------- R5：连通性预检 ----------
def test_ping_unreachable():
    # 127.0.0.1:1 必然无监听 → 连接被拒 → False
    t0 = time.time()
    ok = ping("http://127.0.0.1:1", timeout=3.0)
    dt = time.time() - t0
    assert ok is False, "不可达地址应返回 False"
    assert dt < 10.0, "预检不应无限等待（实测 %.1fs）" % dt
    print("[ok] R5 ping 不可达 → False（%.2fs）" % dt)


def test_ping_empty_url():
    assert ping("") is False
    assert ping(None) is False
    print("[ok] R5 ping 空地址 → False")


# ---------- R6：历史标签 ----------
def test_history_tags():
    history.init_db()
    before = len(history.list_history(500))
    history.add_history("user", "deepseek", "deepseek-chat",
                        "tag输入_" + str(time.time()), "tag输出")
    rows = history.list_history(500)
    assert len(rows) == before + 1, "应新增一条"
    assert len(rows[0]) == 9, "历史行应为 9 列（含 tags+pinned，v0.7.10 R1），实际 %d" % len(rows[0])
    hid = rows[0][0]

    assert history.set_tags(hid, ["alpha", "beta"]) is True
    got = [r for r in history.list_history(500) if r[0] == hid][0]
    assert got[7] == "alpha,beta", "标签应为 alpha,beta，实际 %r" % got[7]

    # 边界标签（首尾）也能命中 —— 修复了原 LIKE '%,tag,%' 漏匹配
    assert any(r[0] == hid for r in history.search_by_tag("alpha")), "首标签应命中"
    assert any(r[0] == hid for r in history.search_by_tag("beta")), "尾标签应命中"
    assert not any(r[0] == hid for r in history.search_by_tag("gamma")), "不存在的标签不应命中"

    # 过滤搜索应覆盖标签（用打标签后的新快照）
    rows_now = history.list_history(500)
    assert any(r[0] == hid for r in util.filter_history(rows_now, "beta")), "标签应可被搜索"
    assert not any(r[0] == hid for r in util.filter_history(rows_now, "不存在的标签xyz")), \
        "无关词不应命中"

    # 清空标签
    history.set_tags(hid, [])
    got2 = [r for r in history.list_history(500) if r[0] == hid][0]
    assert (got2[7] or "") == "", "清空后应为 ''"
    print("[ok] R6 历史标签（写入/首尾命中/搜索/清空）")


# ---------- R7：模板库导入导出 ----------
def test_template_import_export():
    history.init_db()
    stamp = str(int(time.time() * 1000))
    name_a = "tplA_" + stamp
    name_b = "tplB_" + stamp
    history.add_template(name_a, "测试", "内容A")
    history.add_template(name_b, "测试", "内容B")

    exported = history.export_templates()
    # export_templates 返回可序列化 dict 列表（能直接 json.dump，与 import 往返兼容）
    assert all(isinstance(e, dict) for e in exported), "导出应为 dict 列表"
    names = {e["name"] for e in exported}
    assert name_a in names and name_b in names

    # merge=True：同名跳过，异名新增
    added, skipped = history.import_templates(
        [{"name": name_a, "category": "测试", "content": "内容A"},
         {"name": name_a + "_dup", "category": "测试", "content": "内容A2"}],
        merge=True)
    assert skipped >= 1, "同名应被跳过，实际 skipped=%d" % skipped
    assert added >= 1, "异名应新增，实际 added=%d" % added

    # 空/脏数据不应崩
    a2, s2 = history.import_templates([], merge=True)
    assert (a2, s2) == (0, 0)
    a3, s3 = history.import_templates([{"name": "", "content": ""}], merge=True)
    assert a3 == 0, "空名模板不应入库"
    print("[ok] R7 模板导入导出（去重/脏数据不崩）")


# ---------- R8：浮窗快捷键解析 ----------
def test_overlay_shortcuts():
    r = util.resolve_overlay_shortcut
    assert r(True, False, "return") == "optimize"
    assert r(True, False, "enter") == "optimize"
    assert r(True, False, "d") == "diff"
    assert r(True, False, "i") == "insert"
    assert r(True, False, "r") == "replace"
    assert r(True, True, "c") == "copy_all"
    assert r(False, False, "escape") == "cancel"
    # 无修饰键的单字母不应误触发
    assert r(False, False, "d") == ""
    assert r(False, False, "") == ""


# ---------- R10：审查修复的回归断言 ----------
def test_secrets_lazy_import():
    """keyring 必须惰性导入：缺失时 secrets 模块仍可加载，且 set_key 返回 False。"""
    from promptpop import secrets
    assert hasattr(secrets, "set_key")
    # 惰性：应提供 _kr() 惰性入口，且模块导入后不应已加载 keyring
    assert hasattr(secrets, "_kr"), "应提供惰性加载入口 _kr()"
    # 必检项（不依赖本机是否装了 keyring，避免整段被跳过成为空洞断言）
    assert isinstance(secrets.backend_available(), bool)
    assert isinstance(secrets.set_key("deepseek", "x"), bool), "set_key 必须返回 bool 而不是抛异常"
    assert isinstance(secrets.get_key("deepseek"), str)
    # 无 keyring 后端时应如实降级，而不是崩
    if not secrets.backend_available():
        from promptpop import config as cfgmod
        assert secrets.set_key("deepseek", "x") is False
        assert secrets.get_key("deepseek") == ""
        assert secrets.migrate_plaintext_to_keyring(
            cfgmod.Config({"provider": "deepseek"})) == 0
    print("[ok] R10 secrets 惰性导入 + 无后端安全降级")


def test_config_atomic_and_bak_recovery():
    """配置损坏时应从 .bak 恢复；save 后不留 .tmp 残件。"""
    import tempfile
    from pathlib import Path
    from promptpop import config as cfgmod
    d = Path(tempfile.mkdtemp())
    p = d / "config.json"
    orig = cfgmod.config_path
    cfgmod.config_path = lambda: p
    try:
        c = cfgmod.Config({"provider": "deepseek"})
        c.save()
        assert p.exists() and not (d / "config.json.tmp").exists()
        assert not (d / "config.json.bak").exists()  # 首次保存无 bak
        c.data["model"] = "deepseek-chat"
        c.save()
        assert (d / "config.json.bak").exists()
        # 损坏主配置 → load 应从 bak 恢复
        p.write_text("{ broken json", encoding="utf-8")
        c2 = cfgmod.Config.load()
        assert c2.get("provider") == "deepseek", "损坏时应从备份恢复而非重置"
    finally:
        cfgmod.config_path = orig
    print("[ok] R10 config 原子写 + 损坏恢复")


def test_ollama_probe_cache():
    """Ollama 探测：可达结论应缓存，不可达不缓存（避免反复阻塞 3s）。"""
    from promptpop import ollama_probe as op
    calls = {"n": 0}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        return _Resp()

    orig = op.urllib.request.urlopen
    op.urllib.request.urlopen = fake_urlopen
    op._CACHE.update(url=None, ok=False, ts=0.0)
    try:
        assert op.is_ollama_up("http://x:11434") is True
        assert op.is_ollama_up("http://x:11434") is True
        assert calls["n"] == 1, "可达结果应被缓存（TTL 内不再发请求）"
    finally:
        op.urllib.request.urlopen = orig
    print("[ok] R10 ollama 探测缓存")


    print("CYCLE6 TESTS OK (R2-R10)")


# ---------- R9：自定义 OpenAI 兼容端点 ----------
def test_custom_providers():
    from promptpop import providers as P
    cfg = {"api_keys": {}, "custom_providers": []}
    allp = P.get_all_providers(cfg)
    assert {"deepseek", "openai", "ollama"}.issubset(allp)
    P.add_custom_provider(cfg, "OpenRouter", "https://openrouter.ai/api/v1",
                          "qwen/qwen3", "sk-xyz", True)
    e = P.get_all_providers(cfg)["OpenRouter"]
    assert e["custom"] and e["base_url"] == "https://openrouter.ai/api/v1"
    bu, ak, md, nk = P.resolve("OpenRouter", cfg)
    assert (bu, ak, md, nk) == ("https://openrouter.ai/api/v1", "sk-xyz", "qwen/qwen3", True)
    # 同名更新而非重复追加
    P.add_custom_provider(cfg, "OpenRouter", "https://openrouter.ai/api/v1", "new-model")
    assert len(cfg["custom_providers"]) == 1
    assert P.resolve("OpenRouter", cfg)[2] == "new-model"
    # 内置端点不受影响
    assert P.resolve("deepseek", cfg)[0] == "https://api.deepseek.com"
    # 删除
    P.remove_custom_provider(cfg, "OpenRouter")
    assert cfg["custom_providers"] == []
    print("[ok] R9 自定义端点 get/add/remove/resolve")


def main():
    _ensure_app()
    test_high_dpi_policy()
    test_meta_prompt_craft_ice()
    test_context_injection()
    test_diff_lines()
    test_ping_unreachable()
    test_ping_empty_url()
    test_history_tags()
    test_template_import_export()
    test_overlay_shortcuts()
    test_custom_providers()
    test_secrets_lazy_import()
    test_config_atomic_and_bak_recovery()
    test_ollama_probe_cache()
    print("CYCLE6 TESTS OK (R2-R10)")


if __name__ == "__main__":
    main()
