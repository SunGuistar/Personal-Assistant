# 开发计划（Development Plan）

## 现行流程调整（2026-11-11）

用户确认移除晨报助手与 Memory 管理及生成依赖，保留历史表/记录；旧验收记录中的相关功能仅代表当时状态，不是当前要求。

国内/国际仅从中新网对应页面官方热点排行取前 10 条，详情时间筛选和事件去重后不足不凑数，不使用新浪、归档或其他补充来源。AI 保留 AIHOT 最新日报完整标题链接及既有降级、快照逻辑。采集策略 `cnn_official_hot10_v3_ai_daily` 使旧国内/国际候选失效，历史保留。

核心流程改为资讯整理、个人数据准备、GoalAnalysis、ActionSuggest、Editor、七维评价和发布；移除每日 TechResearch，通用 RAG 不删除。两个 Subagent 实际绑定只读历史工具；个人源按已确认正式配置只读加载，缺失不推断为无进展。七维 `decision_score_v2` 依据结构化材料与正文评价，无法验证维度为 null，评价失败仍可发布。具体业务及架构分别以 V0.6 产品设计和 Architecture 为准。下文旧阶段记录是历史证据，不代表现行流程。

用户确认删除独立事实校验节点、提示词、链接/发布时间校验和发布阻塞逻辑。现行为“主编整合 → 质量评价 → 发布”，进度为 10 阶段。报告接口不再返回 fact_check；数据库历史列和历史任务记录保留，新报告不写入。下文已有验收记录中的事实校验描述属于调整前证据，不代表当前要求。


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

> 依据：`Docs/V2/V0.6产品设计.md`（最终产品需求）、`Docs/V2/V0.6.1额外信息.md`（技术约束）、`Docs/technical-validation-v2/`（T1–T22 及专项验证，部分已归档/移除）。
> 开发方式：一次性授权、分阶段自动推进；每阶段真实测试 PASS 后进入下一阶段（规则见任务书 §七）。
> 阶段状态图例：`[ ]` 未开始 / `[~]` 进行中 / `[P]` PASS / `[B]` BLOCKED。每阶段记录：修改文件、测试命令与结果、关键决定、遗留项。

## 阶段总览

| 阶段 | 目标 | 状态 |
|---|---|---|
| 1 基础设施与数据隔离 | 晨报模块骨架、独立 SQLite+迁移、hub 只读访问、配置与状态、FastAPI 集成 | [~] |
| 2 资讯获取与处理 | 新浪热榜/中新网精选/AIHOT/热摸爽接入、窗口过滤、事件去重、失败处理 | [ ] |
| 3 RAG、索引与缓存 | Qdrant 双 Collection、混合检索、统一 RAG Tool、Embedding 复用、阶段缓存、一致性检查 | [ ] |
| 4 LangGraph 与 Agent 工作流 | 全流程编排、三个 Subagent、模型路由、Checkpoint、幂等 | [ ] |
| 5 晨报生成与质量保障 | 五部分正文、五维评价 quality_score_v1、版本与快照、用量统计 | [ ] |
| 6 前端与用户交互 | 三页导航、生成进度与阶段详情、重新生成、SSE 日志、深色模式 | [ ] |
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
- `graph/workflow.py`：LangGraph 编排（快照→并行资讯/个人分析→技术研究∥目标分析 Subagent→建议 Subagent→主编→质量评价→发布），AsyncSqliteSaver Checkpoint，阶段缓存指纹复用，幂等防重复主报告
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

### 阶段 5 完成记录（2026-11-10 PASS）

- **修改文件**：`api/report.py`（report/history/regenerate/usage）、`services/report_service.py`（clear_cache 语义、personal_ctx_override、个人事件快照）、`api/runs.py`、`tests/test_morning_stage5_report.py`
- **测试**：5 个全过——主报告/指定版本/404、历史列表与评价绑定、regenerate 409 防并发、缓存语义（manual 复用/full 清空）、个人快照落库与用量 API 聚合；全量回归 **239 passed**
- **关键决定**：缓存清理策略 auto=清、manual=复用、full=显式清（API 传参）；质量分等权四舍五入已在图节点实现（quality_score_v1）；用量字段缺失记 None 不臆造 0

## 阶段 6：前端与用户交互

**任务与文件**：
- `web/src/pages/MorningReportPage.tsx`（晨报正文/质量评价/历史晨报三导航 + 右栏助手与日志）
- `web/src/api/morning.ts`（类型化 API 客户端）
- 助手对话 API（`api/assistant.py`：SSE 流式 + Memory 提议需确认）
- SSE 运行日志（`api/logs.py`：EventSource，run_logs 实时推送）
- App.tsx 路由与导航接入；深色模式适配
- `web/src/test/` 前端单测（Vitest）

**验收**：三页数据真实来自后端；状态一致（正文/评价/历史指向同版本）；SSE 日志可断开重连；Memory 管理可用；tsc + vitest + build 全过。

### 阶段 6 完成记录（2026-11-10 PASS）

- **修改文件**：后端 `api/{assistant,logs}.py`；前端 `web/src/api/morning.ts`、`pages/MorningReportPage.tsx`、`App.tsx`、`components/layout/AppLayout.tsx`（导航+/morning 隐藏全局右栏）、`tailwind.config.js`（darkMode class）、`index.css`、补 `web/index.html`（仓库此前缺失未跟踪）、`test/morning.test.tsx`
- **测试**：后端 4 个全过（SSE 全量+done、after_id 续传、助手无 Key 降级、MEMORY_PROPOSAL 块解析后剥离）；前端 Vitest **50 passed**（9 文件）、tsc + vite build 通过；后端全量回归 **243 passed**
- **关键决定**：Memory 提议经 SSE 结构化块返回、前端确认后才 POST 写入（source=chat，满足"征得确认"）；SSE 日志以 after_id 续传支持断线重连；深色模式用 html.dark class 策略，晨报页内切换并持久化 localStorage
- **修复**：lucide 无 Morning 图标（改 Sunrise）；助手系统提示词花括号与 format 冲突；TestClient 对无限流需用 client.stream 有界读取
- **遗留**：右栏助手/日志在 <lg 窄屏隐藏（PC 优先，符合 V2.0 范围）

## 阶段 7：完整系统验收

**任务**：
- 端到端真实流程：真实采集（已有）→ 真实索引（DashScope Embedding + fastembed）→ 真实生成（manual/DashScope；auto/DeepSeek 视时段）→ 前端展示
- 08:00 调度与防重复触发测试（模拟时间触发 job_fn）
- 故障注入：源失败降级、索引脏阻塞、事实校验阻塞（单测已覆盖，补端到端核验）
- 现有模块回归（243 passed 已含）
- V0.6 需求逐项对照、使用说明、人工验收指南
- 交付报告

### 阶段 7 完成记录（2026-11-10 PASS）

- **修改文件**：`services/report_service.py`（LLM 输入截断、双 Collection 预建、发布版本索引同步、dirty 恢复路径）、`graph/workflow.py` + `graph/prompts.py`（主编补 URL、事实校验规则层化）、`tests/test_morning_stage7_scheduler.py`、证据目录 `Docs/technical-validation-v2/morning-report-dev/`
- **LIVE 端到端**：真实采集（550 条）→ 真实索引（DashScope dense + BM25 sparse，23 点）→ 真实生成（qwen-flash，17.7s）→ 事实校验通过 → 评价 96 分 → 主报告发布 → 历史晨报索引 9 块 → RAG 检索命中。证据 `stage7_live_e2e.json`，复跑 `e2e_live_run.py`
- **关键决定**：事实校验=规则层（孤儿链接/窗口外引用，确定性）+LLM 层（事实一致性），避免模型日期比较错误；主编输入必须带材料内 URL（此前模型编造链接被真实拦截两次——系统按设计工作）；manual 复用缓存导致 run5 用量调用少，属预期
- **回归**：后端 244 passed；前端 50 passed；build 通过
- **上线观察项**（不阻塞交付）：DeepSeek auto 路径首跑（明早 08:00 低谷）、连续多日覆盖、中新网结构监控告警、Subagent 接 RAG 工具、Docker Desktop 自启

### 进度面板改造完成记录（2026-11-11 PASS）

- **定位转变**：实时日志模块 → 晨报生成进度面板（默认简洁展示完整流程/当前进度/关键信息，点击阶段出悬浮详情）
- **数据层**：追加迁移 v2 `run_stages`（12 阶段定义映射真实 LangGraph 工作流；status=pending/running/success/warning/failed/skipped/interrupted；last_event_at 活跃心跳）；技术日志仍在 run_logs，历史数据兼容
- **后端**：`services/progress.py` 线程安全跟踪器（会话工厂短会话，跨 Subagent 线程）；API `/progress`（快照+服务器时钟+卡住阈值）、`/progress/active`（活动任务判定）、`/progress/stream`（seq 单调增量推送，终态先持久化后 done）；启动清理 run+stages interrupted；structured_data 脱敏（掩 sk-*、剔 prompt/messages）
- **前端**：ProgressPanel 重写（容器 h-2/5 不变）：状态徽章/开始时间/运行时长/阶段计数/当前阶段；完整 12 阶段列表（完成✓/进行中高亮/等待灰/警告黄/失败红/降级跳过/中断标注）；并行 Subagent 独立行+“并行执行”组标识；底部最近动态 3 条；点击阶段→面板内悬浮详情窗（阶段目的/起止/耗时/尝试次数/结果/原因 + 可折叠技术详情 + 复制按钮）；卡住提醒（running 阶段超阈值未更新→黄条提示，不判失败）
- **互斥**：两个生成按钮活动任务期间同时禁用（前端 5s 轮询 /progress/active + 提交后立即切换 run_id）；后端 409 兜底（DB 判重，多标签页绕不过）
- **测试**：后端新增 9 个全过（生命周期/快照/脱敏/活动判定/SSE 快照+done+增量去重/409 互斥/interrupted 清理/run_generate 全阶段流转）；前端新增 4 个全过（阶段列表/并行标识/高亮/悬浮详情/按钮禁用与恢复）；全量回归后端 253、前端 54、tsc+build 通过
- **面板尺寸验证**：section 保持 `h-2/5` 与原右栏结构，无新增常驻技术日志区（证据：组件类名未变 + 前端测试通过）
- **已知缺口（不属本次范围）**：Subagent 仍 tools=[]（RAG 工具未挂载，已在验收报告记录）；自动重试 3 次未实现；`npx vitest` 与 npm test 环境不一致时 jsdom 曾丢失（重装恢复），建议用 npm test

### 停止生成功能完成记录（2026-11-11 PASS）

- **协作式取消**：`services/cancel.py`（CancelToken/GenerationCancelled，不杀线程）；Runner 注册令牌（`token_for/request_cancel`，submit 创建、终态清理）；工作流全部 9 节点入口 + report_service 四阶段 + 采集源之间设安全检查点；取消后后续节点不执行、不发布不完整晨报
- **状态与数据**：run.status 新增 stopping/cancelled（迁移 v3：run_records.stop_reason/stopped_at）；stop API（`POST /runs/{id}/stop`）UPDATE 守卫防与自然完成竞态、幂等；stopping 属活动态（互斥不松）；Runner 统一落 cancelled：进行中阶段标记"用户主动停止"、stop 日志（请求时间/停止阶段/已完成标记）、缓存与历史数据全保留；进程重启时 stopping→cancelled（确认已停止）
- **前端**：第三按钮「停止生成」（无任务禁用/活动可用/点击 confirm 确认框/请求后"正在停止…"禁用，任务终态自动复位）；状态标签补"正在停止/已停止"；**修复进行中按钮误恢复 bug**：SSE 每帧同步 active（此前只初次/done 同步，轮询间隙有启用窗口）
- **测试**：后端 5 个（工作流中途取消后续节点不执行且不发布、Runner cancelled 终态+阶段标记+缓存保留+令牌清理、stop API 幂等+stopping 互斥+终态守卫、竞态自然完成不改、采集源间协作式停止）；前端 2 个（停止流程+确认取消）；全量回归后端 258、前端 56、tsc+build 通过
