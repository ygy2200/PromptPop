"""模型下拉自动拉取回归测试（离屏）。

覆盖 v0.7.5 之后「为什么选不了具体模型」的体验修复：
  - 切换 provider / 首次显示浮窗时自动拉取模型列表（无需手动点 ⟳）
  - 拉取成功写入缓存，命中缓存不再重复请求
  - 拉取失败（没 Key / 网络不通 / 端点不支持）静默保持手填，不打扰

运行： QT_QPA_PLATFORM=offscreen python tests/test_overlay_models.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from promptpop.config import Config  # noqa: E402
from promptpop.overlay import OverlayWindow  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _new_win():
    _app()
    cfg = Config()
    w = OverlayWindow(cfg)
    w.config.save = lambda: None  # 隔离：不写真实配置目录
    w._sync_from_config()         # 模拟初始化，让 model_box 有默认值
    return w


def test_models_fetched_fills_and_caches():
    w = _new_win()
    w._on_models_fetched(["deepseek-chat", "deepseek-reasoner"], silent=True)
    assert w.model_box.count() == 2
    assert w._model_cache["deepseek"] == ["deepseek-chat", "deepseek-reasoner"]


def test_models_fetched_empty_silent_no_cache():
    w = _new_win()
    # 静默模式空列表不应写入缓存、不应抛异常
    w._on_models_fetched([], silent=True)
    assert "deepseek" not in w._model_cache
    # 显式点 ⟳（silent=False）也只走提示分支，不崩
    w._on_models_fetched([], silent=False)
    assert "deepseek" not in w._model_cache


def test_ensure_models_cache_hit_no_fetch():
    w = _new_win()
    w._model_cache = {"deepseek": ["a", "b"]}
    with mock.patch.object(w, "_on_fetch_models") as m:
        w._ensure_models(silent=True)
        m.assert_not_called()
    assert w.model_box.count() == 2


def test_ensure_models_miss_triggers_fetch():
    w = _new_win()
    w._model_cache = {}
    with mock.patch.object(w, "_on_fetch_models") as m:
        w._ensure_models(silent=True)
        m.assert_called_once_with(silent=True)


def test_provider_changed_triggers_fetch():
    w = _new_win()
    idx = w.provider_box.findData("openai")
    assert idx >= 0
    with mock.patch.object(w, "_on_fetch_models") as m:
        w.provider_box.setCurrentIndex(idx)
        # 切换 provider 后应自动拉取新 provider 的模型列表
        m.assert_called()


def test_first_show_no_key_no_fetch():
    # 默认 deepseek 需 Key 但未配置 → 首次显示不应自动拉取（免浪费/静默失败）
    w = _new_win()
    assert w._models_shown_once is False
    with mock.patch.object(w, "_ensure_models") as m:
        w.show_at_cursor()
        m.assert_not_called()
    assert w._models_shown_once is True


def test_first_show_ollama_triggers_fetch():
    # Ollama 无需 Key → 首次显示应自动拉取
    w = _new_win()
    w.config.set("provider", "ollama")
    w._sync_from_config()
    with mock.patch.object(w, "_ensure_models") as m:
        w.show_at_cursor()
        m.assert_called_once_with(silent=True)
    assert w._models_shown_once is True


def test_first_show_with_key_triggers_fetch():
    # 已配置 Key 的 provider → 首次显示应自动拉取
    w = _new_win()
    w.config.set("api_keys", {"deepseek": "sk-test", "openai": "", "ollama": ""})
    w._sync_from_config()
    with mock.patch.object(w, "_ensure_models") as m:
        w.show_at_cursor()
        m.assert_called_once_with(silent=True)


def test_first_show_once_only():
    # 再次显示不应重复触发
    w = _new_win()
    w.config.set("provider", "ollama")
    w._sync_from_config()
    with mock.patch.object(w, "_ensure_models") as m:
        w.show_at_cursor()
        m.assert_called_once()
    with mock.patch.object(w, "_ensure_models") as m2:
        w.show_at_cursor()
        m2.assert_not_called()


def test_quick_optimize_pipeline():
    # 工具条「优化」一键直达：显示浮窗 + 自动开始优化 + 预填选中文本
    w = _new_win()
    with mock.patch.object(w, "show_at_cursor") as m_show, \
         mock.patch.object(w, "_on_optimize") as m_opt:
        w.quick_optimize("  划词选中的指令  ")
        m_show.assert_called_once()
        m_opt.assert_called_once()
    assert "划词选中的指令" in w.input_box.toPlainText()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
