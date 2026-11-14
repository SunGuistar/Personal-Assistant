"""进程内模块就绪状态；仅记录非敏感诊断，不存用户数据。"""
import threading
import time

MODULE_PREFIXES = {
    "morning": ("/api/morning",),
    "wechat": ("/api/wechat", "/api/cleanup"),
    "reading": ("/api/books", "/api/notes"),
    "github": ("/api/github",),
}


class ModuleStartup:
    def __init__(self):
        self.started = time.perf_counter()
        self.home_ready = False
        self.lock = threading.Lock()
        self.modules = {name: dict(status="loading", duration_s=0.0, error=None) for name in MODULE_PREFIXES}

    def finish(self, name, started, error=None):
        with self.lock:
            self.modules[name] = dict(status="failed" if error else "ready",
                                      duration_s=round(time.perf_counter() - started, 4), error=error)

    def snapshot(self):
        with self.lock:
            return dict(home_ready=self.home_ready, elapsed_s=round(time.perf_counter() - self.started, 3),
                        modules={name: item.copy() for name, item in self.modules.items()})

    def for_path(self, path):
        for name, prefixes in MODULE_PREFIXES.items():
            if any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes):
                return name
        return None
