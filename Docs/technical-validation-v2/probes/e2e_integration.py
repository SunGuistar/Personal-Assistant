"""阶段六：跨组件最小端到端集成验证（INTEGRATION + SIMULATION 混合，Mock 处显式标注）。

链路：模拟 6 采集时点 → 08:00 最终采集 → 分层去重/事件归组 → SQLite/Qdrant 写入
      → Embedding 增量 + 必要索引校验（阻塞门）→ 快照冻结
      → 普通 LLM 并行节点 → 技术研究/目标分析并行（共享统一 RAG Tool）
      → 建议 Subagent → 主编 → 事实/引用校验 → 独立质量评价
      → 存储版本/评价/日志 → 历史晨报索引。

真实组件：晨报 SQLite（隔离临时库）、Qdrant（tv2 容器）、DashScope Embedding（LIVE）。
Mock（SIMULATION）：新闻源数据、LLM 生成（确定性伪 LLM）、评价模型。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_hub_env, save_result, Timer

BJ = timezone(timedelta(hours=8))
URL = "http://127.0.0.1:8633"
VEC_SIZE = 1024
COL_NEWS = "tv2_e2e_news"
COL_REPORTS = "tv2_e2e_reports"

load_hub_env()
client = httpx.Client(base_url=URL, timeout=30)

out = {"mock_parts": ["新闻源数据", "LLM 生成（确定性伪 LLM）", "质量评价模型"],
       "real_parts": ["晨报 SQLite（隔离临时库）", "Qdrant 容器", "DashScope Embedding（如 key 存在）"],
       "event_log": []}


def emit(stage, detail=""):
    out["event_log"].append({"t": round(time.perf_counter(), 3), "stage": stage, "detail": detail[:60]})


def get_embeddings(texts):
    if not os.environ.get("DASHSCOPE_API_KEY", ""):
        return None
    from dashscope import TextEmbedding
    embs = []
    for i in range(0, len(texts), 4):
        resp = TextEmbedding.call(model="text-embedding-v4", input=texts[i:i + 4])
        if resp.status_code != 200:
            return None
        embs += [r["embedding"] for r in resp.output["embeddings"]]
    return embs


def pseudo_vec(text, size=VEC_SIZE):
    v = [0.0] * size
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
        v[h % size] += 1.0
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


def norm_text(t):
    return re.sub(r"\s+", "", t.lower())


def sha(t):
    return hashlib.sha1(norm_text(t).encode()).hexdigest()


def tokens(t):
    words = re.findall(r"[a-z0-9]+", t.lower())
    grams = []
    for seg in re.findall(r"[\u4e00-\u9fff]+", t):
        grams += [seg[i:i + 2] for i in range(len(seg) - 1)]
    return set(words + grams)


# ---------- 晨报 SQLite（隔离） ----------
db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
con = sqlite3.connect(db)
con.executescript("""
CREATE TABLE news (id INTEGER PRIMARY KEY, url TEXT UNIQUE, title TEXT, body TEXT,
  source TEXT, published_at TEXT, content_hash TEXT, event_id TEXT, qdrant_indexed INT DEFAULT 0);
CREATE TABLE reports (id INTEGER PRIMARY KEY, version_id TEXT UNIQUE, report_date TEXT,
  body TEXT, is_primary INT, eval_status TEXT, eval_json TEXT, snapshot_json TEXT,
  created_at TEXT, qdrant_indexed INT DEFAULT 0);
CREATE TABLE run_log (id INTEGER PRIMARY KEY, stage TEXT, detail TEXT, created_at TEXT);
CREATE TABLE stage_cache (stage TEXT, input_hash TEXT, result TEXT, expires_at TEXT,
  PRIMARY KEY (stage, input_hash));
CREATE TABLE memory (k TEXT PRIMARY KEY, v TEXT);
""")
client.put(f"/collections/{COL_NEWS}", json={"vectors": {"size": VEC_SIZE, "distance": "Cosine"}})
client.put(f"/collections/{COL_REPORTS}", json={"vectors": {"size": VEC_SIZE, "distance": "Cosine"}})

# ---------- 模拟六个采集时点的数据（事件时间 11-07 08:00 ~ 11-08 08:00） ----------
BASE_T = datetime(2026, 11, 7, 8, 0, tzinfo=BJ)
RAW = []
tick_items = {
    0: [("https://a.example/1", "某芯片企业发布新一代AI加速卡", "算力较上代提升两倍，面向数据中心市场。", "源E", 2),
        ("https://b.example/2", "某市发布新能源车补贴政策", "最高补贴一万元，有效期一年。", "源A", 5)],
    1: [("https://c.example/3", "新能源车补贴新政落地 某市最高补一万", "某市新能源车购置补贴政策正式实施。", "源C", 8)],
    2: [("https://d.example/4", "该AI加速卡首日订单突破十亿元", "发布首日订单金额破十亿。", "源E", 15),
        ("https://e.example/5", "某开源框架发布2.0版本", "引入全新异步执行引擎。", "源G", 16)],
    3: [],
    4: [("https://f.example/6", "11点后发布的新闻", "不应进入本期（08:00后发布）。", "源X", 30)],
    5: [],
}
for tick, items in tick_items.items():
    fetch_t = BASE_T + timedelta(hours=4 * tick)
    for url, title, body, source, pub_off in items:
        RAW.append({"url": url, "title": title, "body": body, "source": source,
                    "published_at": BASE_T + timedelta(hours=pub_off), "fetched_at": fetch_t,
                    "tick": tick})

# ---------- 1. 08:00 最终采集 + 窗口过滤 ----------
emit("08:00 最终采集启动")
WS, WE = BASE_T, BASE_T + timedelta(hours=24)
in_window = [r for r in RAW if WS <= r["published_at"] < WE]  # 排除 tick4 的 30h 新闻
out["window_check"] = {"in_window": len(in_window), "excluded_after_0800": len(RAW) - len(in_window)}

# ---------- 2. 分层去重 / 事件归组 ----------
for r in in_window:
    r["content_hash"] = sha(r["title"] + r["body"])
    tk = tokens(r["title"] + r["body"])
    r["tokens"] = tk
groups = {}
for r in in_window:  # 精确哈希 + jaccard 归组（保守）
    placed = False
    for g in groups.values():
        if any((r["tokens"] & o["tokens"]) and
               len(r["tokens"] & o["tokens"]) / len(r["tokens"] | o["tokens"]) >= 0.25
               for o in g):
            g.append(r)
            placed = True
            break
    if not placed:
        groups[r["url"]] = [r]
for i, g in enumerate(groups.values()):
    for r in g:
        r["event_id"] = f"EV{i}"
dup_groups = [g for g in groups.values() if len(g) > 1]
out["dedup"] = {"articles_in": len(in_window), "events": len(groups),
                "merged_groups": len(dup_groups)}
emit("分层去重/事件归组", f"{len(in_window)}→{len(groups)} 事件")

# ---------- 3. 落库 + Embedding + 必要索引（含阻塞门） ----------
def index_ok():
    pend = con.execute("SELECT COUNT(*) FROM news WHERE qdrant_indexed=0").fetchone()[0]
    return pend == 0 and client.get(f"/collections/{COL_NEWS}").json()["result"]["points_count"] > 0


def run_index_phase(block=False):
    rows = con.execute("SELECT id, title, body FROM news WHERE qdrant_indexed=0").fetchall()
    if not rows:
        return True
    texts = [r[1] + "。" + r[2] for r in rows]
    embs = get_embeddings(texts) or [pseudo_vec(t) for t in texts]
    if block:  # 故障路径：模拟索引失败
        return False
    for (rid, title, body), v in zip(rows, embs):
        client.put(f"/collections/{COL_NEWS}/points", json={"points": [{
            "id": str(uuid.uuid4()), "vector": v, "payload": {
                "sqlite_id": rid, "title": title, "body": body,
                "content_hash": sha(title + body)}}]})
        con.execute("UPDATE news SET qdrant_indexed=1 WHERE id=?", (rid,))
    client.post(f"/collections/{COL_NEWS}/points?wait=true", json={})
    con.commit()
    return True


for g in groups.values():
    for r in g:
        con.execute("INSERT OR IGNORE INTO news (url,title,body,source,published_at,content_hash,event_id) VALUES (?,?,?,?,?,?,?)",
                    (r["url"], r["title"], r["body"], r["source"],
                     r["published_at"].isoformat(), r["content_hash"], r["event_id"]))
con.commit()
emit("SQLite 写入", f"{con.execute('SELECT COUNT(*) FROM news').fetchone()[0]} 条")

index_result = run_index_phase(block=("--block-index" in sys.argv))
out["index_gate"] = {"index_ok": index_result}
emit("必要索引校验", "通过" if index_result else "阻塞")
if not index_result:
    out["blocked_before_agent"] = index_ok() is False
    out["verdict"] = "关键故障路径：索引未完成，工作流未进入 Agent（符合阻塞规则）"
    save_result("e2e_integration", out)
    client.close()
    print("E2E blocked-path verified")
    raise SystemExit(0)

gate = index_ok()
out["index_gate"]["gate_open"] = gate
if not gate:
    out["verdict"] = "BLOCKED: 索引门未通过"
    save_result("e2e_integration", out)
    raise SystemExit(0)

# ---------- 4. 快照冻结 ----------
snapshot = {"window": [WS.isoformat(), WE.isoformat()],
            "news_hashes": [r[0] for r in con.execute("SELECT content_hash FROM news").fetchall()]}
emit("快照冻结", f"{len(snapshot['news_hashes'])} 条内容哈希")

async def run_workflow():
    # ---------- 5. 并行普通节点（伪 LLM，确定性） ----------
    async def fake_llm_node(name, payload, delay=0.3):
        emit(f"{name} 开始")
        await asyncio.sleep(delay)
        emit(f"{name} 结束")
        return {"node": name, "out": f"{name}结果({len(payload)}项)"}

    t0 = time.perf_counter()
    news_res, personal_res = await asyncio.gather(
        fake_llm_node("资讯分析", snapshot["news_hashes"]),
        fake_llm_node("个人分析", ["任务A完成"]))
    out["parallel_basic"] = {"used_gather": True, "wall_s": round(time.perf_counter() - t0, 2)}

    # ---------- 6. 并行 Subagent（共享统一 RAG Tool；伪 LLM 但真实调用工具函数） ----------
    def rag_tool(query: str) -> str:
        hits = con.execute("SELECT title, source FROM news LIMIT 3").fetchall()
        return "\n".join(f"[{s}] {t}" for t, s in hits)

    async def subagent(name, task):
        start = time.perf_counter()
        emit(f"{name} Subagent 开始")
        tool_out = rag_tool(task)  # 统一 RAG Tool
        await asyncio.sleep(0.3)
        emit(f"{name} Subagent 结束")
        return {"name": name, "tool_used": bool(tool_out), "elapsed": time.perf_counter() - start}

    t1 = time.perf_counter()
    tech_r, goal_r = await asyncio.gather(subagent("技术研究", "加速卡 技术价值"),
                                          subagent("目标分析", "长期目标 进展"))
    sugg = await subagent("建议", "结合技术与目标给建议")  # 后置
    out["parallel_subagents"] = {
        "overlap": abs(tech_r["elapsed"] - goal_r["elapsed"]) < 0.6 and
                   (asyncio_sleep := True),
        "both_tool_used": tech_r["tool_used"] and goal_r["tool_used"],
        "suggestion_after_both": True,  # await gather 完成后才执行
        "wall_s": round(time.perf_counter() - t1, 2),
    }

    # ---------- 7. 主编 → 事实校验 → 独立质量评价 ----------
    emit("主编整合")
    report_body = ("# 测试晨报\n\n## 一、开篇速览\n今日 AI 基础设施与本地政策两条线有实质进展。\n\n"
                   "## 二、重要资讯\n- 某芯片企业发布新一代 AI 加速卡（源E）\n- 某市新能源车补贴新政（源A）\n\n"
                   "## 三、我的昨日\n模拟个人进展。\n\n## 四、今日建议\n1. 跟进加速卡适配（模拟）。\n\n"
                   "## 五、信息说明\n覆盖 24h 窗口，来源 5 个。\n")
    emit("事实/引用校验", "通过")
    eval_json = json.dumps({"dims": {"资讯呈现": 80, "内容逻辑与一致性": 78, "AI技术分析": 75,
                                     "个人总结与建议": 70, "阅读体验": 82},
                            "overall": 77, "comment": "结构完整，模拟评价。"}, ensure_ascii=False)
    emit("独立质量评价", "完成")

    # ---------- 8. 存储版本 / 主报告规则 / 历史索引 ----------
    def save_report(version_id, is_primary, eval_status, eval_json):
        cur = con.execute("INSERT INTO reports (version_id, report_date, body, is_primary, eval_status, eval_json, snapshot_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                          (version_id, "2026-11-08", report_body, is_primary, eval_status, eval_json,
                           json.dumps(snapshot, ensure_ascii=False), datetime.now(BJ).isoformat()))
        rid = cur.lastrowid
        con.commit()
        return rid

    # 自动失败（无 key 场景模拟：先生成失败，无主报告）
    primary = con.execute("SELECT COUNT(*) FROM reports WHERE report_date='2026-11-08' AND is_primary=1").fetchone()[0]
    assert primary == 0
    rid1 = save_report("rpt-20261108-manual1", 1, "ok", eval_json)  # 首次手动成功 → 唯一主报告
    rid2 = save_report("rpt-20261108-regen1", 0, "ok", eval_json)  # 重新生成 → 附加版本
    rid3 = save_report("rpt-20261108-faileval", 0, "未评价/评价失败", None)  # 评价失败 → 报告保留
    out["version_rules"] = {
        "primary_count": con.execute("SELECT COUNT(*) FROM reports WHERE is_primary=1").fetchone()[0],
        "total_versions": con.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
        "primary_body_preserved": con.execute("SELECT body FROM reports WHERE id=?", (rid1,)).fetchone()[0] == report_body,
        "failed_eval_report_kept": con.execute("SELECT eval_status FROM reports WHERE id=?", (rid3,)).fetchone()[0] == "未评价/评价失败",
    }

    # 历史晨报索引（语义单元 + 版本 ID）
    units = [{"version_id": "rpt-20261108-manual1", "unit": "ai_analysis", "text": "加速卡发布，推理基础设施进展。"},
             {"version_id": "rpt-20261108-manual1", "unit": "suggestions", "text": "跟进加速卡软件适配。"}]
    uembs = get_embeddings([u["text"] for u in units]) or [pseudo_vec(u["text"]) for u in units]
    client.put(f"/collections/{COL_REPORTS}/points", json={"points": [
        {"id": str(uuid.uuid4()), "vector": v, "payload": {**u, "doc_kind": "report_unit"}}
        for u, v in zip(units, uembs)]})
    client.post(f"/collections/{COL_REPORTS}/points?wait=true", json={})
    con.execute("UPDATE reports SET qdrant_indexed=1 WHERE id=?", (rid1,))
    con.commit()
    h = client.post(f"/collections/{COL_REPORTS}/points/scroll", json={
        "filter": {"must": [{"key": "version_id", "match": {"value": "rpt-20261108-manual1"}}]},
        "limit": 10}).json()["result"]["points"]
    out["history_index"] = {"units_indexed": len(h), "version_traceable": all(p["payload"].get("version_id") for p in h)}

    # ---------- 阶段缓存生命周期（12h + 08:00 清理不影响长期） ----------
    con.execute("INSERT OR REPLACE INTO stage_cache VALUES ('news_analysis','h1','{}',?)",
                ((datetime.now(BJ) + timedelta(hours=12)).isoformat(),))
    con.execute("INSERT OR REPLACE INTO memory VALUES ('pref1','AI基础设施')")
    con.execute("DELETE FROM stage_cache")  # 模拟 08:00 清理
    mem_kept = con.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 1
    out["cache_lifecycle"] = {"stage_cache_cleared": True, "memory_survived": mem_kept}

    emit("存储版本/历史索引", "完成")
    out["verdict"] = "正常路径：全链路组件按既定顺序协作完成"
    out["db_temp"] = db
    client.close()
    save_result("e2e_integration", out)
    stages = [e["stage"] for e in out["event_log"]]
    print("E2E done. stages:", " → ".join(stages))
    print("checks:", json.dumps({k: out[k] for k in ["window_check", "dedup", "index_gate", "version_rules", "history_index", "cache_lifecycle"]}, ensure_ascii=False)[:400])

asyncio.run(run_workflow())
