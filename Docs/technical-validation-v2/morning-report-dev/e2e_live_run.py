# -*- coding: utf-8 -*-
"""阶段 7 LIVE 端到端：真实索引（DashScope Embedding + fastembed BM25）→ 真实生成（manual/qwen-flash）。

使用开发库 data/morning_report.db（阶段 2 LIVE 采集的 550 条真实数据）；
hub 经只读连接访问主工作区 hub.db。
证据输出：Docs/technical-validation-v2/morning-report-dev/stage7_live_e2e.json
"""
import json
import sys
import time

sys.path.insert(0, r"E:\wechat-LangGraph-v2")
import env_bootstrap
env_bootstrap.load_hub_env()

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.morning_report import db as mr_db
from app.morning_report.config import get_mr_settings
from app.morning_report.models import (Evaluation, ReportVersion, RunRecord,
                                       TokenUsage)
from app.morning_report.services import report_service

HUB_DB = "E:/wechat-LangGraph/data/hub.db"
OUT = Path(r"Docs/technical-validation-v2/morning-report-dev/stage7_live_e2e.json")

mr_engine = mr_db.make_engine(r"E:\wechat-LangGraph-v2\data\morning_report.db")
mr_db.run_migrations(mr_engine)
mr_sf = mr_db.make_session_factory(mr_engine)

# hub 只读连接（主工作区真实库；mode=ro 双保险）
hub_engine = create_engine(f"sqlite:///{HUB_DB}?mode=ro",
                           connect_args={"uri": True, "check_same_thread": False})
hub_sf = sessionmaker(bind=hub_engine, expire_on_commit=False)

settings = get_mr_settings()

with mr_sf() as mr:
    run = RunRecord(run_date="2026-11-10", kind="generate", status="pending")
    mr.add(run)
    mr.commit()
    run_id = run.id

print(f"[e2e] run_id={run_id}，开始真实生成（manual/qwen-flash）…", flush=True)
t0 = time.perf_counter()
with mr_sf() as mr:
    result = report_service.run_generate(
        mr, run_id, settings, mode="manual",
        hub_session_factory=hub_sf, mr_session_factory=mr_sf)
elapsed = round(time.perf_counter() - t0, 1)
print(f"[e2e] 完成，耗时 {elapsed}s：{json.dumps(result, ensure_ascii=False)[:300]}", flush=True)

with mr_sf() as mr:
    run = mr.get(RunRecord, run_id)
    versions = mr.execute(select(ReportVersion).where(
        ReportVersion.run_id == run_id)).scalars().all()
    evs = mr.execute(select(Evaluation)).scalars().all()
    usages = mr.execute(select(TokenUsage).where(TokenUsage.run_id == run_id)).scalars().all()
    evidence = {
        "run_id": run_id,
        "elapsed_s": elapsed,
        "run_status": run.status,
        "result": result,
        "versions": [{"id": v.id, "version_no": v.version_no, "is_primary": v.is_primary,
                      "content_head": v.content_md[:200]} for v in versions],
        "evaluations": [{"version_id": e.version_id, "status": e.status,
                         "composite": e.composite} for e in evs],
        "token_usage_calls": len(usages),
        "token_usage_totals": {
            "input": sum(u.input_tokens or 0 for u in usages),
            "output": sum(u.output_tokens or 0 for u in usages),
        },
    }
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[e2e] 证据已保存: {OUT}", flush=True)
print(json.dumps(evidence, ensure_ascii=False, indent=2)[:1200], flush=True)
