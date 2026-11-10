# 开发计划（Development Plan）

各阶段需要实现的功能规划。本文档只回答"做哪些功能"，不承担进度追踪职责（开发历史由 Git 记录）；需求规则见 `PRD.md`，技术设计见 `Architecture.md`。

V1（个人助手基础版）已全部完成并归档，见 `Docs/archive/DEVELOPMENT_PLAN_V1.md`。本文档管理下一阶段开发规划。

## 核心定位

**个人数据驱动的智能工作助手。**

整合计划、备忘、重要信息、阅读记录及未来接入的 GitHub 等个人数据，利用 AI 进行信息整理、关联分析、总结和建议。

核心目标：

1. **实际提效**：减少信息整理、工作回顾和计划制定的时间。
2. **简历展示**：通过真实功能体现 Agent 工作流、工具调用、上下文管理、长期记忆、检索策略、执行追踪和效果评测能力。

开发原则：

- 以真实需求为导向，避免无意义地堆砌 AI 功能。
- 普通程序能够高效解决的问题，不强行使用 LLM 或 Agent。
- 优先实现有实际价值的功能，再考虑技术复杂度。
- 不强制采用 Multi-Agent。
- AI 分析和建议应尽可能基于可追溯的个人数据。
- 涉及重要数据修改时，应保留人工确认机制。

已确认的开发原则（下一阶段开发以此为准）：

1. 长期记忆以 SQLite 为权威存储，Chroma 仅在需要语义检索时作为辅助索引；第一版不强制向量化。
2. 每日简报采用应用启动或首次进入首页时检查、后台按需生成的方式，不引入常驻守护进程。
3. 保持本文档的功能规划定位，不记录开发或验收状态。
4. 不提前开发未批准阶段的功能。
5. GitHub 数据接入采用官方 REST API，不引入 GitHub MCP（未来 Agent 需要自主查询时再评估）。

## 阶段划分总览

| 阶段 | 内容 | 优先级 |
|---|---|---|
| 阶段一 | GitHub 数据集成 | P0 |
| 阶段二 | 每日工作简报 | P0 |
| 阶段三 | 长期记忆与跨数据源分析 | P1 |
| 阶段四 | Agent 工程能力增强 | P1 |
| 开发工具优化（独立事项） | Claude-y Comment Detector | P1 |

划分理由：GitHub 开发活动是后续 Agent 分析（简报、回顾类功能）缺少的关键外部数据源，且是纯数据管道（认证→同步→持久化→查询接口），不依赖任何 Agent 能力，先行打通；每日简报依赖 GitHub 数据与现有业务数据，排阶段二；长期记忆与工程增强服务于已有功能的体验与成本，在数据通路稳定后建设。

## 阶段一：GitHub 数据集成（P0）

- 认证与安全配置（Token 经 `~/.personal-hub/.env`，不入 Git）。
- 个人仓库信息获取（基础元数据）。
- Commit 数据获取与标准化。
- Pull Request 数据获取与标准化。
- Issue 数据获取与标准化。
- GitHub 活动数据（events）获取。
- SQLite 持久化：标准化表结构，统一经 Alembic 迁移。
- 增量同步与同步游标（复用 sync_cursors 模式），重复数据处理（确定性 ID 幂等）。
- API 限流处理、超时与重试、同步失败恢复（任务状态机落库）。
- 提供统一的 GitHub 数据查询 Service 接口，供后续 Agent/简报使用。

**技术方案已确定：GitHub 官方 REST API，不接入 GitHub MCP。** 当前任务是数据获取、同步与持久化，REST API 更适合明确的同步需求；未来 Agent 确实需要自主查询 GitHub 时，再评估 MCP。

## 阶段二：每日工作简报（P0）

- 汇总每日计划、长期计划、随手备忘、重要信息、阅读管理等已有数据，接入 GitHub 开发活动。
- Agent 自主分析值得关注的信息：进展、问题、风险及潜在关联。
- 根据实际情况提供可执行建议；支持多轮对话和用户补充。
- 生成简洁的每日工作简报并持久化，首页展示。
- 采用应用启动或首次进入首页时检查、后台按需生成的方式，不引入常驻守护进程。

设计原则：不展示所有统计数据，不强制每个模块生成总结，不强制固定数量的发现或建议，不制造没有数据依据的结论；Agent 只读分析，未经用户确认不得修改业务数据。

## 阶段三：长期记忆与跨数据源分析（P1）

- SQLite 作为长期记忆权威存储，Chroma 作为可选的语义检索辅助索引。
- 历史活动与当前任务关联；跨周期、跨数据源上下文分析。
- 用户偏好、项目背景和历史决策持久化；跨会话使用。

## 阶段四：Agent 工程能力增强（P1）

- Agent 执行追踪与效果评测（核心任务测试样例、质量/检索/完成度评估）。
- 模型调用与 Token 成本优化（多模型配置、按任务复杂度选模、成本记录分析）。
- 智能信息分类（对话输入→判断归属模块→用户确认，留存纠正记录）。
- 多 Agent 协作：有实际需求时再引入，不预先建设。

## 开发工具优化（独立事项，P1）

- Claude-y Comment Detector：纳入开发工具与代码质量优化规划，目标是改善 AI 生成代码注释和技术文档的质量。
- 本阶段仅记录规划，不安装、不集成、不讨论具体使用方式。
- 参考：https://github.com/citelao/dotfiles/blob/main/dotfiles/.chezmoitemplates/skills/claudy-comment-detector/SKILL.md
- 此项为开发工具优化，独立于 Agent 业务功能阶段，不与上述阶段耦合。

## 未批准的后续规划（继续保留）

以下需求未经批准，不排入当前开发：

- 移动端支持（形态待评估：PWA / 手机浏览器访问 / 独立客户端）
- 备份与恢复系统（覆盖 hub.db + 聊天两库 + Chroma + 笔记附件 + 配置）
- 重复启动处理

另：PRD §4 与 Architecture §7 中的 V2.0 演进约束（局域网 → 认证 → HTTPS → 移动端同步）继续有效，不提前实现。

---

# V2 专项：今日晨报 V2.0 开发计划（2026-11-10 启动）

> 依据：`Docs/V0.6产品设计.md`（最终产品需求）、`Docs/V0.6.1额外信息.md`（技术约束）、`Docs/technical-validation-v2/`（T1–T22 及专项验证）。
> 开发方式：一次性授权、分阶段自动推进；每阶段真实测试 PASS 后进入下一阶段（规则见任务书 §七）。
> 阶段状态图例：`[ ]` 未开始 / `[~]` 进行中 / `[P]` PASS / `[B]` BLOCKED。每阶段记录：修改文件、测试命令与结果、关键决定、遗留项。

## 阶段总览

| 阶段 | 目标 | 状态 |
|---|---|---|
| 1 基础设施与数据隔离 | 晨报模块骨架、独立 SQLite+迁移、hub 只读访问、配置与状态、FastAPI 集成 | [~] |
| 2 资讯获取与处理 | AIHOT/中新网归档/热摸爽接入、窗口过滤、去重、失败处理 | [ ] |
| 3 RAG、索引与缓存 | Qdrant 双 Collection、混合检索、统一 RAG Tool、Embedding 复用、阶段缓存、一致性检查 | [ ] |
| 4 LangGraph 与 Agent 工作流 | 全流程编排、三个 Subagent、模型路由、Checkpoint、幂等 | [ ] |
| 5 晨报生成与质量保障 | 五部分正文、事实校验、五维评价 quality_score_v1、版本与快照、用量统计 | [ ] |
| 6 前端与用户交互 | 三页导航、晨报助手与 Memory、重新生成、SSE 日志、深色模式 | [ ] |
| 7 完整系统验收 | 端到端真实验证、调度测试、故障注入、回归、交付报告 | [ ] |

## 阶段 1：基础设施与数据隔离

**目标**：模块骨架 + 独立 DB 读写 + hub 只读 + API 集成。

**任务与文件**：
- `app/morning_report/__init__.py`、`config.py`（MRSettings：DB 路径、Qdrant URL、Collection 名、模型端点、调度开关）
- `app/morning_report/db.py`（独立 engine + 轻量迁移器，迁移脚本 `migrations/`）
- `app/morning_report/models.py`（news_items / reports / report_versions / memories / stage_cache / token_usage / run_records / run_logs / index_state / event_groups）
- `app/morning_report/schemas.py`（pydantic）
- `app/morning_report/services/hub_readonly.py`（hub.db 只读：每日任务、长期计划、重要信息、阅读记录）
- `app/morning_report/api/__init__.py` + `status.py`、`memory.py` 基础路由
- `app/main.py` 集成（独立 engine/session 存 app.state；调度器后续阶段接入）
- `tests/test_morning_stage1_*.py`

**验收标准**：
- 隔离库自动建表迁移，可读写；hub.db 无写入/结构变更（测试断言 hub 文件 hash 或只读会话）
- 现有 pytest 全套仍绿（回归）
- 新模块单测全绿

**证据**：`tests/` 结果输出；本节"完成记录"。

## 阶段 2–7 详细任务

（各阶段开始时展开填写，完成后补"完成记录"。）

## 完成记录

（每阶段 PASS 后追加。）

### 阶段 1 完成记录（2026-11-10 PASS）

- **修改文件**：`app/morning_report/`（`__init__/config/db/models/schemas` + `api/{__init__,deps,status,memory}.py` + `services/{__init__,hub_readonly}.py`）、`app/main.py`（`_init_morning_report`）、`tests/test_morning_stage1_infra.py`
- **测试**：`pytest tests/test_morning_stage1_infra.py` 6 passed；全量回归 **212 passed**（LIVE/INTEGRATION 隔离库）
- **关键决定**：晨报独立 SQLite 用内置轻量迁移器（`schema_migrations` 版本表，v1 建全部核心表）；hub 只读经 `app.state.session_factory` 纯 SELECT；晨报路由直接挂 app（不进全局 api_router，避免重复装配）；MRSettings 独立 `PH_MR_` 前缀
- **遗留**：调度器（阶段 4 接入）；新闻模型本阶段已建，采集管线阶段 2 实现

### 阶段 2 完成记录（2026-11-10 PASS）

- **修改文件**：`app/morning_report/adapters/{__init__,http_common,aihot,chinanews,remoshuang}.py`、`services/{news_pipeline,runner}.py`、`api/runs.py`、`api/__init__.py`、`app/main.py`（mr_runner）、`tests/test_morning_stage2_collect.py`
- **测试**：新增 6 个全过（适配器解析/分类、管线全流程、跨源去重、失败降级、runner 冲突）；LIVE 真实采集一轮（窗口 2026-11-09 08:00~11-10 08:00）：aihot 20 条游标翻页成功、中新网 1006 条、热摸爽 60 条线索、窗口内 490 条、存 550 条、零源失败；证据 `Docs/technical-validation-v2/morning-report-dev/stage2_live_collect.json`
- **关键决定**：HTTP 统一走 httpx（项目标准，respx 可 mock）；外交部/中方 纳入涉外时政关键词；热摸爽条目无发布时间→仅线索（published_at=None，不入窗口统计）；事件归组阈值 bigram Jaccard 0.55（保守，只打组标不删记录）
- **修复**：runner 并发判重需排除自身 run_id；respx 对 requests 无效（已切 httpx）
- **遗留**：中新网归档页当前日期含未来条目由窗口过滤兜住；AIHOT 摘要使用规则在阶段 5 摘要生成时遵守（聚合摘要不当事实证明）

## 阶段 3：RAG、索引与缓存

**任务与文件**：
- `adapters/embedding.py`：DashScope text-embedding-v4（1024 维，batch≤10）+ fastembed BM25 sparse；EmbeddingProvider 协议可注入假实现
- `services/qdrant_store.py`：双 Collection 建配（dense cosine + sparse IDF）、幂等 upsert（内容哈希 ID）、混合检索（prefetch+RRF）、payload 过滤
- `services/rag_tool.py`：统一 RAG Tool（dense+BM25、来源回溯、可选 Query 改写/回退、Rerank 暂缺省关闭可配置）
- `services/stage_cache.py`：输入指纹 + 12h TTL + 新轮清理
- `services/index_sync.py`：AI 资讯→tech_news、晨报版本→reports 分块索引、index_state 一致性检查（必要索引失败→阻塞标记）
- `tests/test_morning_stage3_rag.py`（真本地 Qdrant，tmp_mr_* 集合用后清理；Embedding 用假实现）

**验收标准**：真实向量写入/检索/更新/删除；Embedding 复用（同 hash 不重复调用）；缓存命中/失效/到期；索引一致性检查能识别不一致并置 dirty/failed。

### 阶段 3 完成记录（2026-11-10 PASS）

- **修改文件**：`adapters/embedding.py`（DashScope dense + fastembed sparse + EmbeddingCache 复用）、`services/{qdrant_store,rag_tool,stage_cache,index_sync}.py`、`tests/test_morning_stage3_rag.py`
- **测试**：6 个全过（真本地 Qdrant，tmp_mr_* 集合用后清理；假 Embedding）——混合检索命中、幂等 upsert（重复同步点数不变）、Embedding 缓存复用零新增、Query 改写成功/失败回退、索引 dirty 阻塞、阶段缓存 TTL/清理、晨报分块索引与过滤检索、缺失索引检测
- **关键决定**：点 ID = uint64 确定性哈希（Qdrant 拒绝负 int64）；Rerank 默认关闭（T21 结论），接口预留；必要索引异常抛 IndexUnavailableError 由工作流阻塞
- **回归**：全量 pytest 结果见 stage3 回归输出（随阶段 4 提交前复核）

## 阶段 4：LangGraph 与 Agent 工作流

**任务与文件**：
- `services/llm_router.py`：DeepSeek/DashScope 路由 + 允许时段检查 + Thinking 节点级配置 + Token 落库
- `graph/prompts.py`：系统提示词（版本化 prompt_version）
- `graph/workflow.py`：LangGraph 编排（快照→并行资讯/个人分析→技术研究∥目标分析 Subagent→建议 Subagent→主编→事实校验→质量评价→发布），AsyncSqliteSaver Checkpoint，阶段缓存指纹复用，幂等防重复主报告
- `services/report_service.py`：run_generate 入口（08:00 流程编排：清缓存→采集→索引检查→图执行）
- `api/runs.py` 增加 generate 触发；调度器（APScheduler 每日 08:00）
- `tests/test_morning_stage4_graph.py`（FakeLLM + 假 Embedding + 真 Checkpoint 恢复/并行/后置断言）

**验收标准**：并行关系正确；三 Subagent 固定调用；建议后置；时段外正式模型拒绝且不换模型；失败节点恢复重跑语义不重复写主报告；缓存命中跳过重算。

### 阶段 4 完成记录（2026-11-10 PASS）

- **修改文件**：`services/{llm_router,report_service,scheduler}.py`、`graph/{prompts,workflow,subagents}.py`、`api/runs.py`（generate 触发）、`app/main.py`（调度器接线）、`tests/test_morning_stage4_graph.py`
- **测试**：10 个全过——全流程发布（主报告唯一/五维等权 87 分/quality_score_v1）、附加版本不覆盖主报告、事实校验阻塞发布、评价失败不阻塞、Subagent 降级、并行真实重叠（事件轨迹）、阶段缓存跨轮复用、Checkpoint 注入失败后 `invoke(None)` 恢复、时段规则（周二 08:00 允许/15:00 禁止/周六允许）、report_service 级 blocked；全量回归 **234 passed**
- **关键决定**：图入口需显式两条 START 边（info/personal 并行）；提示词 JSON 花括号 `{{}}` 转义；同步节点统一 `asyncio.to_thread` 包装保证真并行；LangGraph 默认节点重试存在，Subagent 节点内部 try/except 走降级、主编等关键节点不捕获（传播出图触发恢复）；生产路径必须注入 mr/hub 双 factory
- **修复**：调度器 start/shutdown 幂等（两次 startup 事件场景）
- **遗留**：正式模型（auto）真实调用验证留待阶段 7 低谷时段或手动 manual（DashScope）验证；Rerank 未接入（默认关闭）

## 阶段 5：晨报生成与质量保障

**任务与文件**：
- `api/report.py`：GET /report（当日/历史/指定版本）、GET /evaluation、POST /regenerate（reuse/full 高级重算）
- `services/report_service.py`：regenerate 语义（full=缓存全清重算；默认可复用阶段缓存）、个人事件快照落 personal_event_snapshots
- 用量统计查询 API（TokenUsage 聚合）
- `tests/test_morning_stage5_report.py`

**验收**：主报告唯一与版本切换；重新生成不覆盖历史；评价绑定版本；0-3 条建议约束；费用/耗时字段可查。
