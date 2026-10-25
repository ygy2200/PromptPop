"""LLM 流式优化引擎（QThread）。

健壮性（依据 openai SDK 最佳实践）：
- 客户端超时（默认 600s 太久，改用可配置的超时）；
- 可取消：cancel() 置停止位，循环检出后关流退出；
- 错误分类：仅瞬时错误（连接/超时/限流/5xx）指数退避+抖动重试，auth/invalid 等快速失败；
- 流在 finally 中 close，避免连接泄漏；
- token 用量（stream_options include_usage）；
- 代理支持（http_client=httpx.Client(proxies=...)），适配校园网等需代理场景；
- 报错脱敏（不泄露 API Key）+ 可操作错误指引。
"""
import random
import threading
import time

import httpx
from PySide6.QtCore import QThread, Signal


def _transient_errors():
    """openai 的瞬时错误类（延迟导入，缺库不影响其它层）。"""
    try:
        from openai import (APIConnectionError, APITimeoutError, RateLimitError,
                            InternalServerError)
        return (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)
    except Exception:
        return ()


def _esafe(e):
    """异常对象的字符串化防御：第三方库的异常可能 __str__ 自己就抛——
    在 except 块里再崩会直接杀死 worker 线程。"""
    try:
        return str(e)
    except Exception:
        return type(e).__name__


def classify_error(e):
    """返回 (kind, message)。kind ∈ transient / auth / invalid / unknown。

    分类优先级：
    1) 瞬时错误（连接/超时/限流/5xx）——含测试可注入的 FakeTransient；
    2) openai SDK 的鉴权/请求错误类（延迟导入；缺库或被测异常非该类则跳过），
       用异常类型而非消息文本判定更稳（消息文案随 SDK 版本变化）；
    3) 退化为基于消息文本的分类（未装 openai 或异常类不在已知集合时）。
    """
    name = type(e).__name__
    transient = _transient_errors()
    if transient and isinstance(e, transient):
        return "transient", "%s：%s" % (name, _esafe(e))
    # openai SDK 的鉴权/请求错误类：用类型判定，避免依赖易变的消息文案
    try:
        from openai import (AuthenticationError, BadRequestError,
                            NotFoundError, PermissionDeniedError,
                            UnprocessableEntityError)
        if isinstance(e, (AuthenticationError, PermissionDeniedError)):
            return "auth", "API Key 无效或无权（%s）" % name
        # 422（内容/参数校验失败）同属 invalid：落 unknown 会误导成「需配代理」
        if isinstance(e, (BadRequestError, NotFoundError, UnprocessableEntityError)):
            return "invalid", "请求被拒绝（%s）：%s" % (name, _esafe(e))
    except Exception:
        pass
    try:
        low = _esafe(e).lower()
    except Exception:
        low = ""
    if "api key" in low or "unauthorized" in low or "401" in low or "permission" in low:
        return "auth", "API Key 无效或无权（%s）" % name
    if "400" in low or "invalid" in low or ("content" in low and "filter" in low):
        return "invalid", "请求被拒绝（%s）：%s" % (name, _esafe(e))
    return "unknown", "%s：%s" % (name, low or "（异常不可字符串化）")


HINTS = {
    "transient": "网络/连接不稳定（已自动重试）；持续失败请检查网络或代理。",
    "auth": "请到「设置」检查 API Key 是否正确、有无权限。",
    "invalid": "可能是模型名错误或内容被安全过滤；换模型或调整输入。",
    "unknown": "国际接口（OpenAI/Claude 等）在校园网可能需代理——到「设置」填写代理地址。",
}


def error_hint(kind):
    return HINTS.get(kind, HINTS["unknown"])


def _is_loopback(url):
    """base_url 是否为本机回环地址。

    Ollama 与本地 mock 必须直连；若系统配了 HTTP(S)_PROXY，httpx 默认
    (trust_env=True) 会把 127.0.0.1 也送进代理，导致本机模型请求被代理挡掉、
    线程阻塞在 recv 上。回环地址一律禁用环境代理。
    """
    import urllib.parse as _up
    try:
        host = (_up.urlparse(url or "").hostname or "").lower()
    except Exception:
        return False
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "")


def build_timeout(connect=10.0, read=60.0):
    """拆分连接/读取超时（流式场景 read 应远大于 connect）。

    依据：LLM 流式端点的相邻 chunk 间隔可能很长，单 total 超时要么误杀长生成、
    要么挂死线程；httpx 的 read 是「两次读取之间的不活动超时」语义，正合适。
    负值/0（配置被手改，safe_float 不拦负数）会得到语义未定义的 httpx 超时——
    一律夹到至少 1s。
    """
    c = max(1.0, float(connect))
    r = max(1.0, float(read))
    return httpx.Timeout(connect=c, read=r, write=min(c, 10.0), pool=5.0)


def build_client(api_key, base_url, timeout=60.0, proxy="", connect_timeout=10.0):
    """构造 OpenAI 客户端；有代理则走 httpx.Client(proxy)。

    回环地址（Ollama/本地）强制直连：禁用从环境读取的代理，否则本机模型
    会被代理挡掉、线程卡死在 recv。"""
    from openai import OpenAI
    t = build_timeout(connect_timeout, timeout)
    if _is_loopback(base_url):
        http = httpx.Client(trust_env=False, timeout=t)
        return OpenAI(api_key=api_key, base_url=base_url,
                      http_client=http, max_retries=0)
    if proxy:
        http = httpx.Client(proxy=proxy, timeout=t)
        return OpenAI(api_key=api_key, base_url=base_url,
                      http_client=http, max_retries=0)
    return OpenAI(api_key=api_key, base_url=base_url,
                  timeout=t, max_retries=0)


def consume_stream(stream, on_token, should_stop=None, on_usage=None):
    """消费流并累计全文；should_stop() 为真则中断；on_usage(dict) 收尾 token 用量。
    返回 (全文, 是否收到过任意 token)——后者用于判断「是否已进入生成阶段」。"""
    full = []
    received = False
    for chunk in stream:
        if should_stop and should_stop():
            break
        try:
            usage = getattr(chunk, "usage", None)
        except Exception:
            usage = None
        if usage and on_usage:
            try:
                on_usage({"prompt_tokens": usage.prompt_tokens,
                          "completion_tokens": usage.completion_tokens,
                          "total_tokens": usage.total_tokens})
            except Exception:
                pass
        delta = None
        try:
            if chunk.choices:
                delta = chunk.choices[0].delta.content
        except Exception:
            delta = None
        if delta:
            full.append(delta)
            received = True
            on_token(delta)
    return "".join(full), received


def list_models(base_url, api_key, timeout=10.0, proxy="", connect_timeout=10.0):
    """拉取提供商可用模型（OpenAI 兼容 /models）。失败/不支持返回 []。"""
    client = None
    try:
        client = build_client(api_key, base_url, timeout=timeout,
                             proxy=proxy, connect_timeout=connect_timeout)
        return [m.id for m in client.models.list().data]
    except Exception:
        return []
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def ping(base_url, timeout=5.0, proxy="", connect_timeout=5.0):
    """连通性预检：向 base_url 发一次极短请求，判断模型服务是否可达。

    返回 True 表示「网络层可达」（即使返回 401/403 也视为可达，由后续 worker 报鉴权）；
    仅当连接被拒/超时/DNS 失败（httpx.RequestError）才返回 False。
    Ollama 等本地服务不要求 Key，也适用。
    """
    base_url = (base_url or "").rstrip("/")
    if not base_url:
        return False
    t = build_timeout(connect_timeout, timeout)
    try:
        if _is_loopback(base_url):
            # 回环地址强制直连，禁用环境代理（Ollama 等本地服务）
            with httpx.Client(trust_env=False, timeout=t) as c:
                c.get(base_url, follow_redirects=True)
        elif proxy:
            with httpx.Client(proxy=proxy, timeout=t) as c:
                c.get(base_url, follow_redirects=True)
        else:
            with httpx.Client(timeout=t) as c:
                c.get(base_url, follow_redirects=True)
        return True
    except httpx.RequestError:
        return False
    except Exception:
        # 其它异常（如 HTTPStatusError 4xx/5xx）说明服务在响应，视为可达
        return True


class OptimizeWorker(QThread):
    token = Signal(str)      # 每个增量 token
    done = Signal(str)       # 完整结果
    failed = Signal(str)     # 错误信息（已脱敏 + 操作指引）
    cancelled = Signal()     # 用户取消
    usage = Signal(dict)     # token 用量

    def __init__(self, messages, base_url, api_key, model,
                 temperature=0.3, timeout=60.0, max_retries=2,
                 include_usage=True, proxy="", connect_timeout=10.0):
        super().__init__()
        self.messages = messages
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.max_retries = max_retries
        self.include_usage = include_usage
        self.proxy = proxy
        self._stop = False
        self._stop_event = threading.Event()
        self._stream = None      # 当前流式响应，cancel 时关闭以打断阻塞 recv

    def cancel(self):
        self._stop = True
        self._stop_event.set()   # 立即打断重试退避中的等待
        # 关闭正在进行的流：流式端点偶发卡住（相邻 chunk 间隔过长），
        # consume_stream 只在「收到下一片」时才检查 _stop，阻塞在 recv 上会
        # 一直等到 read 超时（默认 60s）才响应取消。从主线程关掉底层 socket，
        # 让阻塞的 recv 立即报错退出，取消近乎即时。
        st = self._stream
        if st is not None:
            try:
                st.close()
            except Exception:
                pass

    def _should_stop(self):
        return self._stop

    def run(self):
        attempt = 0
        while True:
            stream = None
            client = None
            received_any = False

            def _on_tok(t):
                nonlocal received_any
                received_any = True
                self.token.emit(t)

            try:
                client = build_client(self.api_key, self.base_url,
                                      timeout=self.timeout,
                                      proxy=self.proxy,
                                      connect_timeout=self.connect_timeout)
                kwargs = dict(model=self.model, messages=self.messages,
                              stream=True, temperature=self.temperature)
                if self.include_usage:
                    kwargs["stream_options"] = {"include_usage": True}
                stream = client.chat.completions.create(**kwargs)
                self._stream = stream
                full, _ = consume_stream(
                    stream, _on_tok, self._should_stop,
                    on_usage=lambda u: self.usage.emit(u))
                if self._stop:
                    self.cancelled.emit()
                    return
                self.done.emit(full)
                return
            except Exception as e:  # noqa: BLE001
                if self._stop:
                    self.cancelled.emit()
                    return
                kind, msg = classify_error(e)
                if self.api_key and self.api_key in msg:
                    from . import util
                    msg = util.scrub_secret(msg, self.api_key)
                # 安全重试：仅当「尚未收到任何 token」的连接阶段失败才重试，
                # 避免流式已生成一半时重试导致重复计费（依据 LLM 流式非幂等结论）。
                safe_retry = (kind == "transient" and not received_any
                              and attempt < self.max_retries)
                if safe_retry:
                    attempt += 1
                    backoff = min(8.0, 1.0 * (2 ** attempt)) + random.uniform(0, 1)
                    # 可中断等待：退避中点「取消」就直接退出——
                    # 原先无论是否取消都 continue，取消后仍会真实发出一轮 API 请求
                    if self._stop_event.wait(backoff):
                        self.cancelled.emit()
                        return
                    continue
                if received_any and kind == "transient":
                    msg = ("生成中断（已收到部分内容，为避免重复计费未自动重试）。"
                           "｜ 提示：%s" % error_hint(kind))
                else:
                    msg = "%s ｜ 提示：%s" % (msg, error_hint(kind))
                self.failed.emit(msg)
                return
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                self._stream = None
                # 关闭 httpx 客户端，否则每次请求都留一个连接池（长跑会累积 fd/线程）
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
