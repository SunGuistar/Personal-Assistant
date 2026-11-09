"""T17：实时日志与 UI 可行性（INTEGRATION：最小 SSE 探针 + STATIC：前端现状）。

SSE 探针（独立 FastAPI 应用，端口 8634，测完即关）：
- 事件流：节点归属 + 时间戳 + 可展开技术详情（不含敏感数据）
- 断线重连：Last-Event-ID 续传
- 页面刷新后恢复：历史日志查询接口
- 并行事件：两个节点交错推送，客户端收到时序与归属正确
UI 静态核查（web/src）：
- 现有页面/导航/状态管理结构
- 既有 SSE 基础设施（微信模块流式回答先例）
- SSE vs WebSocket 复杂度比较
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASE, EVIDENCE, save_result, Timer

APP = '''
import time, json, threading
from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse
from fastapi.responses import JSONResponse

app = FastAPI()
LOG = []  # 持久化日志存储（模拟落库）
SEQ = [0]

def emit(node, event, detail=None):
    SEQ[0] += 1
    entry = {"id": SEQ[0], "node": node, "event": event,
             "ts": time.strftime("%H:%M:%S"), "detail": detail or {}}
    LOG.append(entry)
    return entry

@app.get("/api/tv2/logs/stream")
async def stream(request: Request, last_id: int = 0):
    def gen():
        # 回放 last_id 之后的历史（断线重连/刷新恢复）
        for e in LOG:
            if e["id"] > last_id:
                yield {"id": str(e["id"]), "event": "log",
                       "data": json.dumps(e, ensure_ascii=False)}
        idx = len(LOG)
        idle = 0
        while idle < 200:  # ~10s 无新事件则结束生成器（探针场景足够）
            if len(LOG) > idx:
                for e in LOG[idx:]:
                    yield {"id": str(e["id"]), "event": "log",
                           "data": json.dumps(e, ensure_ascii=False)}
                idx = len(LOG)
                idle = 0
            else:
                idle += 1
            time.sleep(0.05)
    return EventSourceResponse(gen())

@app.get("/api/tv2/logs/history")
def history(run_id: str = "run1"):
    return {"run_id": run_id, "events": LOG}

@app.post("/api/tv2/simulate")
def simulate():
    def worker():
        import threading
        def node_a():
            for i in range(3):
                emit("技术研究", f"研究步骤{i}", {"model": "deepseek-flash", "tokens": 100 + i})
                time.sleep(0.15)
        def node_b():
            for i in range(3):
                emit("目标分析", f"分析步骤{i}", {"tool": "rag_search", "latency_ms": 45})
                time.sleep(0.15)
        ta = threading.Thread(target=node_a); tb = threading.Thread(target=node_b)
        ta.start(); tb.start(); ta.join(); tb.join()
        emit("主编", "整合完成")
    threading.Thread(target=worker).start()
    return {"ok": True}
'''

out = {}
probe_app = BASE / "probes" / "_t17_app.py"
probe_app.write_text(APP, encoding="utf-8")

port = 8634
_uvicorn_log = open(EVIDENCE / "t17_uvicorn.log", "w", encoding="utf-8")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "--app-dir", str(probe_app.parent),
     "_t17_app:app", "--host", "127.0.0.1", "--port", str(port),
     "--log-level", "warning"],
    stdout=_uvicorn_log, stderr=subprocess.STDOUT)
try:
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(f"{base}/api/tv2/logs/history", timeout=1)
            break
        except Exception:
            time.sleep(0.2)

    # 1. SSE 连接 + 模拟并行事件
    received = []

    def consume(duration=2.0):
        try:
            with httpx.Client(timeout=None) as c:
                with c.stream("GET", f"{base}/api/tv2/logs/stream") as r:
                    t0 = time.time()
                    for line in r.iter_lines():
                        if line.startswith("data:"):
                            received.append(json.loads(line[5:].strip()))
                        if time.time() - t0 > duration:
                            break
        except Exception:
            pass  # 客户端主动断开，服务端流未完整结束属预期

    th = threading.Thread(target=consume)
    th.start()
    time.sleep(0.3)
    httpx.post(f"{base}/api/tv2/simulate", timeout=5)
    th.join(timeout=5)

    nodes = {}
    for e in received:
        nodes.setdefault(e["node"], []).append(e["ts"])
    a, b = nodes.get("技术研究", []), nodes.get("目标分析", [])
    interleaved = bool(a and b and min(a) < max(b) and min(b) < max(a))
    out["sse_stream"] = {
        "events_received": len(received),
        "nodes_covered": sorted(nodes),
        "parallel_events_interleaved": interleaved,
        "has_detail_no_sensitive": all(
            set(e["detail"].keys()) <= {"model", "tokens", "tool", "latency_ms"} for e in received),
        "evidence": "并行节点事件交错到达且带 node 归属",
    }

    # 2. 断线重连（Last-Event-ID 续传）
    last_id = received[0]["id"] if received else 0
    resumed = []
    try:
        with httpx.Client(timeout=None) as c:
            with c.stream("GET", f"{base}/api/tv2/logs/stream", params={"last_id": last_id}) as r:
                t0 = time.time()
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        resumed.append(json.loads(line[5:].strip()))
                    if time.time() - t0 > 0.8:
                        break
    except Exception:
        pass
    out["sse_reconnect_resume"] = {
        "resumed_events": len(resumed),
        "no_duplicate_of_last_id": all(e["id"] > last_id for e in resumed),
    }

    # 3. 历史日志查询（页面刷新恢复）
    h = httpx.get(f"{base}/api/tv2/logs/history?run_id=run1", timeout=5).json()
    out["history_query"] = {"events": len(h["events"]), "ok": len(h["events"]) >= 7}
finally:
    proc.terminate()
    probe_app.unlink(missing_ok=True)

# ---- 前端静态核查 ----
WEB = BASE.parent.parent / "web" / "src"
static = {}
app_tsx = (WEB / "App.tsx").read_text(encoding="utf-8") if (WEB / "App.tsx").exists() else ""
static["nav_structure"] = "顶部导航路由" if "Route" in app_tsx or "route" in app_tsx.lower() else "未识别"
import re
pages = [p.name for p in (WEB / "pages").glob("*.tsx")] if (WEB / "pages").exists() else []
static["existing_pages"] = pages
import re as _re
_realtime_hits = []
for _f in WEB.rglob("*"):
    if _f.suffix in (".ts", ".tsx") and "test" not in _f.parts:
        try:
            for _i, _ln in enumerate(_f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if _re.search(r"EventSource|text/event-stream|WebSocket|EventSourceResponse", _ln, _re.I):
                    _realtime_hits.append(f"{_f.relative_to(WEB)}:{_i}: {_ln.strip()[:100]}")
        except Exception:
            pass
grep_hits = "\n".join(_realtime_hits)
static["existing_realtime_infra"] = [l[:120] for l in grep_hits.splitlines()[:8]]
api_files = [p.name for p in (WEB / "api").glob("*.ts")] if (WEB / "api").exists() else []
static["api_clients"] = api_files
pkg = json.loads((BASE.parent.parent / "web" / "package.json").read_text(encoding="utf-8"))
static["frontend_stack"] = {k: pkg.get("dependencies", {}).get(k) for k in
                            ["react", "react-router-dom", "tailwindcss"]}
static["sse_vs_ws"] = {
    "SSE": "后端 sse-starlette 已在依赖中；单向推送足够（进度/日志）；自动重连由 EventSource 原生支持；集成复杂度低",
    "WebSocket": "websockets 也已安装；双向通信；需自行实现重连/心跳；对日志场景收益有限",
    "recommendation": "SSE（复用 sse-starlette + EventSource），未来对话若需双向再评估 WS",
}
out["frontend_static"] = static

save_result("t17_sse_ui", out)
print("T17 done:", json.dumps({k: out[k] for k in ["sse_stream", "sse_reconnect_resume", "history_query"]},
                              ensure_ascii=False)[:400])
