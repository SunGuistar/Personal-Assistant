# 今日晨报 V2.0 技术验证最终报告

> 验证轮次：T1–T22 全量；日期：2026-11-08；执行环境：Windows，Conda `agent`（Python 3.13.18）。
> 资料索引：本目录 `README.md`、`environment_audit.md`、`validation_matrix.md`、`reports/stage_1..6`、`results/*.json`、`probes/*.py`、`fixtures/*`。

## 一、执行摘要与总体结论

**总体结论：有条件开始开发。**

关键架构（LangGraph 工作流 + 三个 Subagent + Qdrant 混合检索 + 独立 SQLite + 阶段缓存 + 独立质量评价）的全部核心机制已通过真实组件或高保真模拟验证：22 项中 **PASS 12、PARTIAL 7、BLOCKED 3、FAIL 0**。不存在技术机制层面的阻塞；BLOCKED 三项（T3 国际源、T4 AIHOT、T11 NewsAPI）全部是**网络出口或凭据**问题，且有已实测可用的替代来源。两个需要在开发前补齐的"条件"：① 配置 `DEEPSEEK_API_KEY`（每日自动生成所用，否则正式生成环节无可用模型）；② 解决国际新闻网络出口（代理或替代源）。

## 二、现有项目与运行环境

见 `environment_audit.md` 摘要：FastAPI 0.135 + SQLAlchemy 2/Alembic（hub.db 迁移至 0010）、langgraph 1.1.2/langchain 1.2.12、dashscope、feedparser、chromadb（微信专用）、React 18 + Tailwind 前端、sse-starlette、token_usage 费用记录先例、news 适配器（RSS/HN/GitHub）与 GitHub 集成。缺失：qdrant-client、APScheduler、simhash 类库（本轮经隔离 `.venv-probe` 验证，未污染正式环境）；Docker Desktop 位于 `D:\Docker`（验证时已启动，本轮结束后测试容器已删除）。

## 三、T1–T22 全量验证矩阵

见 `validation_matrix.md`。统计：PASS=12（T7、T9、T10、T12、T13、T14、T15、T16、T18、T19、T20、T22）；PARTIAL=7（T1、T2、T5、T6、T8、T17、T21）；BLOCKED=3（T3、T4、T11）；FAIL=0；NOT_TESTED=0。合计 22。

## 四、六个阶段的验证结果

见 `reports/stage_1_data_sources.md`（采集与个人数据）、`stage_2_storage_search.md`（Qdrant 与 RAG）、`stage_3_agent_models.md`（Agent 与模型）、`stage_4_cache_reliability.md`（缓存与可靠性）、`stage_5_evaluation_ui.md`（质量与 UI）、`stage_6_integration.md`（端到端模拟）。

## 五、关键技术选型建议

| 领域 | 建议 | 依据 |
|---|---|---|
| 向量库 | Qdrant 1.20（Docker，专用 volume，端口自定） | T12 全项通过；原生 sparse/BM25 待生产评估 |
| Embedding | DashScope text-embedding-v4（1024 维） | T13/T20/T21 实测命中良好；注意 batch 为 2 的幂且 ≤10 |
| 生成模型（正式） | DeepSeek API，model=`deepseek-flash`（版本 DeepSeek-V4.1-Flash-1017）；调用前低谷检查（工作日 9–12、14–18 北京为高峰） | T8 官方文档核查 + 检查函数断言 |
| 生成模型（开发/手动） | DashScope `qwen-flash`（免费可用）经 OpenAI 兼容端点；qwen-plus 免费额度已耗尽 | T8 LIVE 实测 |
| 调度 | APScheduler + SQLite jobstore | T19 全项通过；项目无既有调度器 |
| 实时日志 | SSE（sse-starlette + EventSource） | T17 实测断线续传/并行归属/历史恢复 |
| Rerank | 暂缓接真实服务；先以混合检索+按需改写上线 | T21：gte-rerank 调用未通过，代理重排收益不显著 |
| 国内新闻源 | GDELT v2 + 中新网 RSS（正文回溯原站） | T2 实测 |
| AI 资讯源 | hotai.news + HN + GitHub Blog RSS | T4/T5 实测（AIHOT 不可达） |
| 去重 | 三层（规范化哈希 → simhash/MinHash → Embedding 语义归组），保守归并 | T20 无误合并、新进展全保留 |

## 六、性能与检索效果测试结果

- T13：中英文 dense+BM25+RRF 查询全部命中；过滤查询全对；单次检索毫秒级（本地容器）。
- T21（n=8 人工标注，仅相对比较）：基线 Recall@5=0.688 / MRR=0.715；改写延迟 +700ms 且**出现改写幻觉**（编造版本名）；重排（代理）MRR 提升至 0.75 但不显著。**建议默认基础混合检索，复杂查询再启用改写**。
- T18：三份样本综合分 88/36/20，区分度显著；同参数重复评分波动 ≤2 分。
- T20：14 篇样本三层去重总耗时 <1s（不含 Embedding API 时间）；真实 Embedding 4 次调用完成 14 篇。
- T19/T15：调度 next_run_time 精确；并行节点真实并发（窗口相交）。

## 七、已发现的问题与风险

1. **快照污染风险（T7 实测）**：不隔离的快照会被后台采集静默污染——必须内容哈希清单+隔离。
2. **改写幻觉（T21 实测）**：LLM 改写会引入未证实实体名；必须加"不编造"系统约束+偏离检测。
3. **DashScope SDK 旧端点 400（T8 实测）**：vl 等新模型须走 OpenAI 兼容端点。
4. **免费额度风险（T8）**：qwen-plus 免费额度已耗尽；开发期统一用 qwen-flash。
5. **个人历史缺口（T1）**：原库完成时间单值覆盖；备忘/重要信息无完成语义——晨报需自建只读事件快照。
6. **恢复时同 super-step 节点重跑（T15 LangGraph 语义）**：阶段缓存须吸收重复执行，避免重复计费。
7. **LangGraph 嵌套调用注意点**：子 Agent 在异步图内必须 ainvoke；Fake 模型的迭代器状态不可共享（开发测试时注意）。
8. **Qdrant file:// 快照 recover 404（1.20）**：备份恢复用 download+multipart upload。

## 八、阻塞开发的问题及最小修复方案

1. **DEEPSEEK_API_KEY 未配置**（阻塞"每日正式自动生成"链路的真实验证与上线）：在 `~/.personal-hub/.env` 增加 key（DeepSeek 新用户有赠送额度）；随后补跑 `probes/t8_llm_api.py` 中 LIVE 段（脚本已就绪，自动做 3 次以内真实调用）。
2. **国际新闻网络出口**（T3 BLOCKED）：为采集进程配置代理，或先行使用可达国际源（如通过代理验证 BBC RSS 后固定）；在解决前，国际版块可用 GDELT 的英文国际新闻域作为过渡。
3. **NewsAPI 不可用**（T11 BLOCKED，非必需）：已有 GDELT 替代，可不处理；如坚持接入需 key+网络+付费升级（开发者版不可商用）。

以上均不阻塞开发启动，只影响上线/全量验证节点。

## 九、待补充凭据或真实环境验证的事项

- DeepSeek 真实调用（/models、JSON 输出、tool calling、prompt_cache_hit_tokens）。
- BBC 等国际源真实连通与正文抓取（需网络出口）。
- DashScope gte-rerank 可用模型名确认（或选定替代重排方案）。
- AIHOT 真实机制（网络可达后补 T4）。

## 十、正式开发的前置条件

1. 决策：接受"国内=GDELT+中新网 RSS；AI=hotai.news+HN+GitHub Blog"的初始来源组合（可在开发中增删）。
2. 配置 DEEPSEEK_API_KEY（可并行开发，上线前必需）。
3. 解决国际源网络（可并行，上线前必需）。
4. 确认综合分公式（本报告建议等权，待拍板；不阻塞开发）。
5. 在 agent 环境安装正式依赖：qdrant-client、APScheduler（及生产选定的 simhash/datasketch、rank-bm25 或 Qdrant 原生 sparse）。

## 十一、推荐开发顺序与依赖关系

1. **基础设施**：晨报 SQLite Schema + Qdrant 部署 + APScheduler 六时点采集骨架（依赖：无）。
2. **采集与去重**：来源适配器（GDELT/中新网/hotai/HN/GitHub Blog）+ 分层去重 + 落库（依赖 1）。
3. **索引与缓存**：Embedding 复用缓存 + 索引门 + 快照冻结（依赖 2）。
4. **Agent 工作流**：LangGraph 图 + 三 Subagent + 统一 RAG Tool + 阶段缓存 + Checkpoint（依赖 3；可与 5 并行）。
5. **模型接入**：deepseek-flash（低谷门）+ qwen-flash（手动）+ 独立评价（依赖 4）。
6. **校验与版本**：事实校验、主报告/附加版本规则、历史晨报索引（依赖 4）。
7. **前端**：晨报页面三二级导航 + SSE 实时日志 + Memory 对话框（依赖 5/6 的 API）。
8. **故障注入回归**：以 t16 场景为测试基线接入 CI。

## 十二、人工复核指南

1. `validation_matrix.md` 的 22 行状态与统计（合计 22）。
2. `results/t8_llm_api.json`：official_docs_static（deepseek-flash 与低谷时段）与 dashscope 各调用状态码。
3. `results/t7_snapshot.json` 的 checks（尤其 snapshot_not_tampered=true 的警示）与 `results/t14_consistency.json` 的 S3/S9 阻塞证据。
4. `results/t15_langgraph_workflow.json`：run2_parallel 窗口相交 + run2_shared_rag_tool=true。
5. `results/e2e_integration.json`：event_log 顺序、version_rules、history_index。
6. 复跑示例：`D:/miniconda/envs/agent/python.exe Docs/technical-validation-v2/probes/t7_snapshot.py`（零依赖即时可跑）；T12–T14/T21 需先 `docker run -d --name tv2-qdrant -p 8633:6333 -v tv2_qdrant_data:/qdrant/storage qdrant/qdrant`。
7. `git status`：仅新增 `Docs/technical-validation-v2/`；hub.db 与聊天库未被本轮修改（只读访问）。

## 十三、最终可行性判断

**有条件开始开发。** 依据：核心机制（工作流编排、并行 Subagent、混合检索、索引阻塞门、快照隔离、四层缓存分离、故障分级、质量评价、SSE 日志）全部通过实测；无 FAIL；剩余 BLOCKED 均为凭据/网络类外部条件且有替代路径。两个硬条件（DeepSeek key、国际源网络）可在开发周期内并行解决，只卡上线不卡开发。

## 附录：命令、测试数据、证据路径和 V3.0 非阻塞预研

**复跑命令**（解释器 `D:/miniconda/envs/agent/python.exe`，下称 PY）：
```bash
cd Docs/technical-validation-v2
PY probes/t1_hub_schema.py            # T1（只读）
PY probes/t2_cn_sources.py            # T2
PY probes/t3_intl_sources.py          # T3
PY probes/t4_aihot.py                 # T4
PY probes/t5_dailydev_hotai.py        # T5
PY probes/t6_fulltext_aggregation.py  # T6
PY probes/t7_snapshot.py              # T7
PY probes/t8_llm_api.py               # T8（有 DeepSeek key 时自动补 LIVE）
PY probes/t9_indexing.py              # T9（需 Qdrant）
PY probes/t10_stage_cache.py          # T10
PY probes/t11_newsapi.py              # T11
PY probes/t12_qdrant_deploy.py        # T12（自动起 Docker 容器）
PY probes/t13_hybrid_search.py        # T13（.venv-probe）
PY probes/t14_consistency.py          # T14
.venv-probe/Scripts/python.exe probes/t15_langgraph_workflow.py  # T15
PY probes/t16_fault_injection.py      # T16
PY probes/t17_sse_ui.py               # T17
PY probes/t18_quality_eval.py         # T18（真实 API 计费，9 次调用）
.venv-probe/Scripts/python.exe probes/t19_scheduler.py           # T19
.venv-probe/Scripts/python.exe probes/t20_layered_dedup.py       # T20
PY probes/t20_embedding_semantics.py  # T20 LIVE
.venv-probe/Scripts/python.exe probes/t21_rag_modes.py           # T21
PY probes/t22_embedding_cache.py      # T22
PY probes/e2e_integration.py          # 阶段六正常路径
PY probes/e2e_integration.py --block-index  # 阶段六故障路径
```

**测试数据**：`fixtures/t20_dedup_samples.json`（14 篇 10 类）、`fixtures/t21_rag_queries.json`（12 文档 8 标注查询）、`fixtures/t18_sample_reports.json`（3 份匿名晨报）。

**资源消耗记录（真实 API）**：DashScope Embedding：T20 共 4 次调用（14 文本）+ T9 数次 + T13/T21/E2E 若干（小样本级）；qwen-flash 聊天：T21 改写 8 次 + T18 评价 9 次 + T8 探测数次。均为免费/小额范围，未购买任何服务。

**清理**：测试容器 tv2-qdrant 与 volume 已删除；`.venv-probe/` 可整体删除（重装见 README）；临时 SQLite 在系统临时目录；未修改任何正式业务代码、hub.db、聊天库、`.env`、正式 UI。

**V3.0 非阻塞预研**：
1. **Agent 异步执行/并发优化**：当前架构已支持真并行（T15 窗口相交实测），V3.0 可评估跨节点调度与并发工具调用的增量收益，预期收益有限、复杂度中等。
2. **Agentic RAG**：本轮已验证"Subagent 自主调用统一 RAG Tool + 按需改写/重排"，与 Agentic RAG 的核心差异在"自主多轮规划"；当前固定三 Subagent 已覆盖业务需求，V3.0 若研究建议以 T21 指标框架做 A/B，有明确增益再扩展。
3. **Skill 机制**：当前工具（RAG Tool、低谷检查、快照工具）已是事实上的可复用能力单元；V3.0 可先梳理真实复用场景（如"历史建议去重"跨模块复用），再决定是否形式化为 Skills，避免为术语加架构。
