# 今日晨报 V2.0 技术验证（T1–T22）资料目录

> 生成目的：正式开发「今日晨报 V2.0」前的全量技术可行性验证。
> 依据文档：`Docs/V0.5产品设计.md`（产品规则）与 `Docs/完整执行流程_V1.3.md`（执行流程）。
> 验证日期：2026-11-08。执行环境：Windows 10/11，Conda `agent` 环境（Python 3.13.18，解释器 `D:/miniconda/envs/agent/python.exe`）。

## 目录结构

```text
technical-validation-v2/
├── README.md                  # 本文件
├── environment_audit.md       # 现有项目与运行环境审计
├── validation_matrix.md       # T1–T22 验证矩阵（含状态统计）
├── reports/                   # 六个阶段报告
│   ├── stage_1_data_sources.md
│   ├── stage_2_storage_search.md
│   ├── stage_3_agent_models.md
│   ├── stage_4_cache_reliability.md
│   ├── stage_5_evaluation_ui.md
│   └── stage_6_integration.md
├── probes/                    # 可独立重跑的验证脚本
├── fixtures/                  # 人工构造的测试数据（转载样本/标注查询集/匿名晨报）
├── results/                   # 各探针脚本输出的结构化结果（JSON）
├── evidence/                  # 执行日志、抓包摘要、截图说明等证据
└── FINAL_TECHNICAL_VALIDATION_REPORT.md
```

## 复跑方法

1. 解释器统一使用 Conda `agent` 环境：
   `D:/miniconda/envs/agent/python.exe`（或 `cmd /c "D:\miniconda\condabin\conda.bat run -n agent python ..."`）。
2. 阶段二需要 Docker 启动临时 Qdrant 容器（脚本 `probes/qdrant_tv2.sh` / `t12_qdrant_deploy.py` 自动完成，端口 8633，Collection 前缀 `tv2_`）。
3. 个别探针依赖 agent 环境没有的包（qdrant-client、APScheduler 等），使用独立虚拟环境
   `.venv-probe/`（见 `environment_audit.md` §6），不污染正式环境。
4. 涉及真实 API 的探针（T8/T18 等）从 `~/.personal-hub/.env` 经 `env_bootstrap.load_hub_env()` 加载密钥，
   脚本只检测 key 是否存在，不打印密钥；真实调用次数有限并记录消耗。

## 证据规则

- 状态：PASS / PARTIAL / FAIL / BLOCKED / NOT_TESTED。
- 证据类型：LIVE（真实服务/API）、INTEGRATION（真实组件集成）、SIMULATION（Mock/故障注入）、STATIC（代码/文档核查）。
- SIMULATION 与 STATIC 不冒充 LIVE；未取得实际响应不记为真实通过。

## 清理

- 测试 Qdrant 容器 `tv2-qdrant` 与 `tv2_*` Collection 由 T12 脚本创建并在最终验证后删除。
- 隔离测试 SQLite 位于系统临时目录或 `results/` 下，可随时删除，不影响 `data/hub.db` 与聊天两库。
- `.venv-probe/` 可整体删除。
