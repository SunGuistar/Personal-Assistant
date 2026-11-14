"""临时本机启动页；仅监听回环地址，结果送达或超时后退出。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import secrets
import threading
import time


class StartupPage:
    def __init__(self, logger, home_url, initial_elapsed=0.0):
        self.started = time.monotonic() - initial_elapsed
        self.logger = logger
        self.home_url = home_url
        self.messages = []
        self.lock = threading.Lock()
        self.result = {"status": "loading"}
        self.finished = threading.Event()
        self.delivered = threading.Event()
        self.close_lock = threading.Lock()
        self.closed = False
        owner = self
        token = "/startup/" + secrets.token_urlsafe(24)
        status_path = "/api" + token

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def do_GET(self):
                if self.path == token:
                    body = Path(__file__).with_name("startup.html").read_bytes()
                    content_type = "text/html; charset=utf-8"
                elif self.path == status_path:
                    with owner.lock:
                        snapshot = dict(owner.result, messages=owner.messages[-100:],
                                        elapsed_s=round(time.monotonic() - owner.started, 1))
                    body = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
                    content_type = "application/json; charset=utf-8"
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if self.path == status_path and snapshot["status"] != "loading":
                    owner.delivered.set()

            def log_message(self, *args):
                pass

        class PageHandler(logging.Handler):
            def emit(self, record):
                with owner.lock:
                    owner.messages.append(self.format(record))
                    owner.messages = owner.messages[-100:]

        self.handler = PageHandler()
        self.handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}{token}"
        self.status_url = f"http://127.0.0.1:{self.server.server_port}{status_path}"
        self.logger.addHandler(self.handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        # 即使命令行主流程返回，也给浏览器留出读取最终结果的时间。
        threading.Thread(target=self._lifetime, daemon=False).start()

    def finish(self, error=None):
        with self.lock:
            self.result = dict(status="failed", error=error) if error else dict(status="ready", home_url=self.home_url)
        self.finished.set()

    def _lifetime(self):
        self.finished.wait(600)
        self.delivered.wait(30)
        self.close()

    def close(self):
        self.finished.set()
        self.delivered.set()
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
            self.server.shutdown()
            self.server.server_close()
            self.logger.removeHandler(self.handler)
