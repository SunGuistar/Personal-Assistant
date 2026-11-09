"""探针脚本公共件：路径、结果落盘、密钥加载（不打印值）。

所有 T* 脚本输出结构化 JSON 到 results/，便于报告引用与复跑。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # Docs/technical-validation-v2/
RESULTS = BASE / "results"
EVIDENCE = BASE / "evidence"
FIXTURES = BASE / "fixtures"
REPO_ROOT = BASE.parent.parent                          # 仓库根

AGENT_PYTHON = r"D:/miniconda/envs/agent/python.exe"


def load_hub_env() -> dict:
    """经 env_bootstrap 加载 ~/.personal-hub/.env；返回存在性清单（不含值）。"""
    sys.path.insert(0, str(REPO_ROOT))
    import env_bootstrap
    env_bootstrap.load_hub_env()
    keys = ["DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY", "GITHUB_TOKEN",
            "NEWS_API_KEY", "TAVILY_API_KEY", "LANGSMITH_API_KEY"]
    return {k: bool(os.environ.get(k, "").strip()) for k in keys}


def save_result(name: str, payload: dict) -> Path:
    RESULTS.mkdir(exist_ok=True)
    payload = {"probe": name, "run_at": datetime.now(timezone.utc).isoformat(), **payload}
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[saved] {path}")
    return path


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.seconds = round(time.perf_counter() - self.t0, 3)
