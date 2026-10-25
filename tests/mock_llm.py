"""本地 mock LLM server（OpenAI 兼容）。

支持：
- POST /v1/chat/completions：SSE 流式（可选尾附 token 用量块）；
- GET  /v1/models：模型列表；
- GET  /api/tags：Ollama 探活；
- fail_first：前 N 次 POST 返回 503（用于验证瞬时重试）。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def make_mock_server(reply="# Role: 测试\n## Profile\n- 会做 X", chunk=3,
                     usage=True, models=None, fail_first=0):
    state = {"fails": fail_first}

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(obj, ensure_ascii=False).encode())

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path.endswith("/models"):
                ms = models if models is not None else ["mock:latest", "mock:pro"]
                self._json({"object": "list",
                            "data": [{"id": m, "object": "model"} for m in ms]})
            else:  # /api/tags 等
                self._json({"models": [{"name": "mock:latest"}]})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            self.rfile.read(length)
            if state["fails"] > 0:
                state["fails"] -= 1
                self._json({"error": {"message": "mock 503", "type": "server_error"}},
                           status=503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            pieces = [reply[i:i + chunk] for i in range(0, len(reply), chunk)] or [""]
            for piece in pieces:
                obj = {"id": "mock", "object": "chat.completion.chunk", "created": 0,
                       "model": "mock",
                       "choices": [{"index": 0, "delta": {"content": piece},
                                    "finish_reason": None}]}
                self.wfile.write(b"data: " +
                                 json.dumps(obj, ensure_ascii=False).encode("utf-8") +
                                 b"\n\n")
                self.wfile.flush()
            if usage:
                u = {"id": "mock", "object": "chat.completion.chunk", "created": 0,
                     "model": "mock", "choices": [],
                     "usage": {"prompt_tokens": 12, "completion_tokens": 7,
                               "total_tokens": 19}}
                self.wfile.write(b"data: " +
                                 json.dumps(u, ensure_ascii=False).encode("utf-8") +
                                 b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]
