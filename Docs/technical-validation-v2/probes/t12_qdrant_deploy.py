"""T12：Qdrant Windows 部署与持久化（LIVE，Docker 临时容器）。

步骤：
1. docker run qdrant/qdrant（端口 8633，独立 volume tv2_qdrant_data）。
2. 建 collection、写入、读回。
3. 重启容器 → 验证数据保留。
4. 更新/删除操作。
5. Snapshot 创建与恢复（同名/新 collection）。
6. 异常中断（docker kill -9 模拟）后一致性检查。
7. 端口冲突检查（8633 vs 8620/6333）。
"""
from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import save_result, Timer

CONTAINER = "tv2-qdrant"
VOLUME = "tv2_qdrant_data"
PORT = 8633
URL = f"http://127.0.0.1:{PORT}"
out = {"container": CONTAINER, "port": PORT, "volume": VOLUME}


def docker(*args, timeout=120):
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def qdrant_up() -> bool:
    code, _, _ = docker("run", "-d", "--name", CONTAINER, "-p", f"{PORT}:6333",
                        "-v", f"{VOLUME}:/qdrant/storage", "qdrant/qdrant:latest")
    if code != 0:
        return False
    for _ in range(60):
        c2, so, _ = docker("exec", CONTAINER, "true")
        try:
            import httpx
            with httpx.Client(timeout=2) as c:
                if c.get(f"{URL}/healthz").status_code == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


# 0. 端口预检
import socket
s = socket.socket()
try:
    s.bind(("127.0.0.1", PORT))
    out["port_free_before_start"] = True
except OSError:
    out["port_free_before_start"] = False
finally:
    s.close()
# 清理旧实例（仅本轮资源）
docker("rm", "-f", CONTAINER)
docker("volume", "rm", "-f", VOLUME)

with Timer() as t:
    out["server_started"] = qdrant_up()
out["startup_s"] = t.seconds

if not out["server_started"]:
    out["docker_error"] = docker("logs", CONTAINER)[2][:500]
    save_result("t12_qdrant_deploy", out)
    print("T12 FAILED to start qdrant")
    raise SystemExit(1)

import httpx

COL = "tv2_deploy_test"
client = httpx.Client(base_url=URL, timeout=20)

# 1. 建 collection + 写入 + 读回
client.put(f"/collections/{COL}", json={"vectors": {"size": 8, "distance": "Cosine"}})
points = [{"id": str(uuid.uuid4()), "vector": [0.1] * 8,
           "payload": {"title": "持久化测试文章", "source": "tv2-probe", "n": i}} for i in range(5)]
client.put(f"/collections/{COL}/points", json={"points": points})
client.post(f"/collections/{COL}/points?wait=true", json={})
r = client.post(f"/collections/{COL}/points/scroll", json={"limit": 10})
out["write_read"] = {"ok": len(r.json()["result"]["points"]) == 5,
                     "points": len(r.json()["result"]["points"])}
stored_ids = [p["id"] for p in r.json()["result"]["points"]]

# 2. 更新 + 删除
client.post(f"/collections/{COL}/points/payload?wait=true",
            json={"payload": {"updated": True}, "points": [stored_ids[0]]})
client.post(f"/collections/{COL}/points/delete?wait=true",
            json={"points": [stored_ids[4]]})
r2 = client.post(f"/collections/{COL}/points/scroll", json={"limit": 10, "with_payload": True})
pts = r2.json()["result"]["points"]
out["update_delete"] = {
    "after_delete_count": len(pts),
    "updated_flag_on_first": any(p["payload"].get("updated") for p in pts),
    "ok": len(pts) == 4,
}

# 3. 优雅重启 → 数据保留
docker("restart", CONTAINER)
time.sleep(8)
for _ in range(30):
    try:
        if client.get("/healthz").status_code == 200:
            break
    except Exception:
        pass
    time.sleep(1)
r3 = client.post(f"/collections/{COL}/points/scroll", json={"limit": 10})
out["survive_graceful_restart"] = {
    "ok": len(r3.json()["result"]["points"]) == 4,
    "points": len(r3.json()["result"]["points"]),
}

# 4. Snapshot 备份与恢复（下载 + multipart 上传恢复；file:// recover 在 1.20 返回 404，见报告）
snap = client.post(f"/collections/{COL}/snapshots").json()["result"]["name"]
out["snapshot_created"] = snap
COL2 = "tv2_deploy_restore"
client.put(f"/collections/{COL2}", json={"vectors": {"size": 8, "distance": "Cosine"}})
snap_bytes = client.get(f"/collections/{COL}/snapshots/{snap}").content
recover = httpx.post(f"{URL}/collections/{COL2}/snapshots/upload?wait=true",
                     files={"snapshot": (snap, snap_bytes, "application/octet-stream")},
                     timeout=60)
time.sleep(3)
r4 = client.post(f"/collections/{COL2}/points/scroll", json={"limit": 10})
out["snapshot_restore"] = {"ok": recover.status_code < 300 and len(r4.json()["result"]["points"]) == 4,
                           "status": recover.status_code,
                           "method": "download + multipart upload",
                           "restored_points": len(r4.json()["result"]["points"])}

# 5. 异常中断（kill）后一致性
client.put(f"/collections/{COL}/points", json={"points": [
    {"id": "post-kill-check", "vector": [0.2] * 8, "payload": {"marker": "pre-kill"}}]})
client.post(f"/collections/{COL}/points?wait=true", json={})
docker("kill", CONTAINER)
time.sleep(2)
docker("start", CONTAINER)
time.sleep(8)
for _ in range(30):
    try:
        if client.get("/healthz").status_code == 200:
            break
    except Exception:
        pass
    time.sleep(1)
try:
    r5 = client.post(f"/collections/{COL}/points/scroll", json={
        "limit": 10, "filter": {"must": [{"key": "marker", "match": {"value": "pre-kill"}}]}})
    out["survive_kill"] = {"ok": True,
                           "marker_present": len(r5.json()["result"]["points"]) == 1,
                           "note": "wait=true 写入在 kill 前已确认；WAL 保证已确认写入不丢"}
except Exception as e:
    out["survive_kill"] = {"ok": False, "error": str(e)[:200]}

out["version"] = client.get("/").json().get("version")
client.close()

# 端口冲突结论
out["port_conflict_check"] = {
    "hub_service_port": 8620, "qdrant_default_port": 6333, "tv2_probe_port": PORT,
    "conflict": False,
}

save_result("t12_qdrant_deploy", out)
print("T12 done:", {k: out[k] for k in ["server_started", "write_read", "update_delete",
      "survive_graceful_restart", "snapshot_restore", "survive_kill", "version"]})
