# -*- coding: utf-8 -*-
"""Qdrant 开发环境预检：临时 Collection 的功能与持久化验证（T12/T13 场景复核）。

phase1：创建带 dense+sparse 双 named vector 的临时 Collection → 写入/稠密查询/
稀疏检索/RRF 混合检索/更新/删除，断言全部落 results/qdrant_precheck.json。
phase2：容器重启后复核持久化 → 清理临时 Collection（不触碰任何其他数据）。

运行（容器已启动 personal-hub-qdrant 后）：
  python qdrant_precheck.py phase1
  docker restart personal-hub-qdrant && sleep 8
  python qdrant_precheck.py phase2
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from qdrant_client import QdrantClient, models

COL = "tmp_v2_precheck_20261110"
DIM = 8
RES = Path(__file__).resolve().parent.parent / "results" / "qdrant_precheck.json"


def client():
    return QdrantClient(url="http://127.0.0.1:6333", timeout=30)


def dense_vec(*vals):
    v = [0.0] * DIM
    for i in vals:
        v[i] = 1.0
    return v


POINTS = [
    (1, dense_vec(0, 1), [0, 3], {"title": "LangGraph 工作流引擎", "kind": "ai"}),
    (2, dense_vec(1, 2), [1, 4], {"title": "向量数据库混合检索实践", "kind": "ai"}),
    (3, dense_vec(2, 3), [2, 5], {"title": "国际新闻聚合方案验证", "kind": "news"}),
    (4, dense_vec(0, 3), [0, 6], {"title": "晨报生成流水线设计", "kind": "news"}),
]


def phase1():
    c = client()
    out = {"phase": 1, "at_cst": datetime.now(timezone(timedelta(hours=8))).isoformat()}
    if c.collection_exists(COL):
        c.delete_collection(COL)
    c.create_collection(
        COL,
        vectors_config={"dense": models.VectorParams(size=DIM, distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams(
            modifier=models.Modifier.IDF)},
    )
    out["created"] = c.collection_exists(COL)

    c.upsert(COL, points=[
        models.PointStruct(id=pid, vector={"dense": dv, "sparse": models.SparseVector(
            indices=si, values=[1.0] * len(si))}, payload=p)
        for pid, dv, si, p in POINTS])
    out["after_upsert"] = c.count(COL).count
    time.sleep(1)

    # 稠密检索：查 [1,0,...] 应命中点1/点4 方向
    dr = c.query_points(COL, query=dense_vec(0), using="dense", limit=2).points
    out["dense_query"] = {"top_ids": [p.id for p in dr],
                          "pass": dr[0].id in (1, 4)}

    # 稀疏检索（BM25/IDF）：查 indices=[1] 应命中点2
    sr = c.query_points(COL, query=models.SparseVector(
        indices=[1], values=[1.0]), using="sparse", limit=2).points
    out["sparse_query"] = {"top_ids": [p.id for p in sr], "pass": sr[0].id == 2}

    # RRF 混合检索
    hr = c.query_points(COL, prefetch=[
        models.Prefetch(query=dense_vec(0), using="dense", limit=4),
        models.Prefetch(query=models.SparseVector(indices=[1], values=[1.0]),
                        using="sparse", limit=4),
    ], query=models.FusionQuery(fusion=models.Fusion.RRF), limit=3).points
    out["hybrid_rrf"] = {"top_ids": [p.id for p in hr], "pass": len(hr) == 3}

    # 更新：payload 写入 + 向量覆写
    c.set_payload(COL, payload={"updated": True}, points=[3])
    c.upsert(COL, points=[models.PointStruct(
        id=3, vector={"dense": dense_vec(5, 6), "sparse": models.SparseVector(indices=[7], values=[1.0])},
        payload={"title": "国际新闻聚合方案验证（更新版）", "kind": "news", "updated": True})])
    p3 = c.retrieve(COL, ids=[3], with_vectors=True)[0]
    # cosine 距离下 Qdrant 存储归一化向量，正确值 = 1/√2 ≈ 0.7071
    out["update"] = {"payload_updated": p3.payload.get("updated") is True,
                     "vector_updated": abs(p3.vector["dense"][5] - 0.7071) < 1e-3}

    # 删除
    c.delete(COL, points_selector=[1])
    out["delete"] = {"count_after": c.count(COL).count, "pass": c.count(COL).count == 3}
    RES.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


def phase2():
    c = client()
    out = {"phase": 2, "at_cst": datetime.now(timezone(timedelta(hours=8))).isoformat()}
    exists = c.collection_exists(COL)
    out["collection_survived_restart"] = exists
    if exists:
        out["count_after_restart"] = c.count(COL).count
        hr = c.query_points(COL, prefetch=[
            models.Prefetch(query=dense_vec(0), using="dense", limit=4),
            models.Prefetch(query=models.SparseVector(indices=[1], values=[1.0]),
                            using="sparse", limit=4),
        ], query=models.FusionQuery(fusion=models.Fusion.RRF), limit=3).points
        out["hybrid_after_restart"] = {"top_ids": [p.id for p in hr], "pass": len(hr) == 3}
        p3 = c.retrieve(COL, ids=[3], with_vectors=True)[0]
        out["update_survived"] = p3.payload.get("updated") is True
        # 清理：仅删除本测试 Collection
        c.delete_collection(COL)
        out["cleanup_deleted"] = not c.collection_exists(COL)
    out["remaining_collections"] = [x.name for x in c.get_collections().collections]
    prev = json.loads(RES.read_text(encoding="utf-8")) if RES.exists() else {}
    RES.write_text(json.dumps({"phase1": prev, "phase2": out}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    {"phase1": phase1, "phase2": phase2}[sys.argv[1]]()
