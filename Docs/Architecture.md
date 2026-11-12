# 个人助手架构设计文档

本文档是**当前系统技术架构的权威来源**。需求与业务规则见 `PRD.md`，开发进度见 `DEVELOPMENT_PLAN.md`。

## 1. 总体架构

```
┌──────────────────────────────────────────────────────────┐
│ 浏览器 (React SPA, 构建产物由 FastAPI 托管, PC 三栏工作台)    │
└──────────────────┬───────────────────────────────────────┘
                   │ HTTP /api/* (JSON, 127.0.0.1:8620)
┌──────────────────▼───────────────────────────────────────┐
│ FastAPI 应用 (app/)                                        │
│  api/ 路由层 → services/ 业务层 → adapters/ 外部适配层       │
│  tasks/ 后台任务(状态机)   wechat_agent/ 微信模块            │
│  models/ SQLAlchemy   db.py engine + Alembic 迁移          │
└───┬──────────┬──────────────┬──────────────┬──────────────┘
    │          │              │              │
 SQLite     Chroma       微信模块数据          外部源
 hub.db   (VectorStore)  GetWechatInfo/       WeChatDataAnalysis
(业务数据)               DataInfo/ 两库        HN/RSS 等
```

原则：前后端彻底分离；业务逻辑集中在 services 层（不依赖 FastAPI 对象，可单测）；外部系统一律经适配器；长任务异步化；复用优先（微信检索/总结/向量逻辑零重写）。

## 2. 目录结构

```
app/                  FastAPI 后端
├── main.py           # 应用装配：路由、静态资源、启动钩子
├── config.py         # pydantic-settings（PH_ 前缀，默认端口 8620）
├── db.py             # engine、session、Alembic 环境
├── api/              # 路由薄层：校验(in schema) → service → 出 schema
├── services/         # 纯业务逻辑（plans/tasks/reading/news/news_translation/infos/memo/wechat…）
├── adapters/         # wechat_source / news_hn / news_rss / news_common
├── wechat_agent/     # 微信模块：Agent 工具、总结流水线、RAG、同步数据层（D3 迁入）
├── tasks/            # TaskRunner：线程池执行、状态落库、同 kind 409 防重
└── models/           # SQLAlchemy 模型（与 Alembic 迁移一一对应）
web/                  React + TS + Vite 前端（AppLayout 三栏 + 右栏组件）
launcher/             # Windows 启动器（launch.py + .bat/.vbs，纯 ASCII）
data/                 # 运行时数据（gitignore）：hub.db、logs/、reading_notes/
tests/                # pytest（隔离临时库，Mock LLM/外网）
Docs/                 # 本文档等
```

## 3. 模块设计

### 3.1 微信模块（复用为主，适配为辅）

- **对话式交互**：所有输入（含 3 个预置快捷 chips）进入同一个 Agent 流程（D2 单通道）；群名经 list_chats 解析、相对日期经系统提示词机制处理；SSE 流式返回，session_id 关联服务端会话历史（chat_sessions/chat_messages）。Service 层只做 Agent 调用封装、任务状态、报告管理——不替代 Agent 做总结决策。
- **总结**：由 Agent 决策调用 `summarize_chat` 工具触发确定性 map/reduce/final 流水线（后台 job 执行）；禁止 Service 直调 `run_summary` 的旁路。总结按 chat_id 过滤（多群），不改变流水线内部行为。
- **同步**（`sync_cursors` 为唯一游标口径）：重叠窗口（游标时间 -24h）分页拉取 → `(timestamp, message_id)` 稳定 ID 幂等 upsert 原始库 → 归一化（指纹去重）→ **游标只在两步都成功后推进**；随后 `rag_store.incremental_index()`（计数减少才全群重建，否则尾部增量、未变化向量复用）；按日对账补录差异。
- **启动外部程序（D5）**：仅启动设置中配置并校验的 exe；轮询 API 就绪，超时给明确错误。
- 重建的 `normalize_snapshot.py` 与历史归一化库对拍一致；聊天相关 SQLite 一律 `mode=ro`。

### 3.2 资讯模块

抓取（hn 官方 Algolia API / rss feedparser，统一超时重试 UA）→ 归一化 → 去重（url 规范化唯一 + 标题哈希）→ 评分（确定性，见 PRD §2.2）→ `news_items` 短期缓存（只增不删）→ `rank_top_items` 纯查询出 TOP 10（首页与资讯页共用）。

- 刷新：TaskRunner 后台任务（kind `news.refresh`，同 kind 409 防重），单源失败记录后继续；首页只读缓存不触发抓取；刷新失败保留旧缓存。
- 翻译（`news_translation`）：刷新任务成功后 + 启动补发两条路径；仅对 TOP 10 中 `translate_status=''` 的条目批量翻译一次并落库（`title_zh/summary_zh`）；中文原文直接回填；失败标 failed 不重试；成本记 `token_usage`。
- 收藏/已读字段为历史遗留，业务零读写；新闻不参与清理审核。

### 3.3 计划 / 阅读 / 右栏

- 长期计划与每日任务**完全独立**（迁移 0006 移除 plan_id，0 条历史关联）。排序统一为 **未完成优先 > 重要 > 任务类型（daily/feature_add/feature_optimize/idea，迁移 0007 新增 task_type 列，存量默认 daily）> sort_order**：长期计划 `PUT /plans/reorder`（ordered_ids 覆盖全部活动计划，按位置写 sort_order）；每日任务**无手动排序接口/入口**——sort_order 仅由创建与移入追加（max+1）决定，同组内按创建先后展示。已完成任务置底（内部完成时间倒序）。完成可反复切换（取消完成清除 completed_at，移除原 history_readonly 限制）。不提供跨日期移动：任务逾期即自然延续到后续日期视图（无 `POST /tasks/{id}/move`；历史已移入任务保留 moved_from_date 溯源展示）。
- 阅读：书籍重要标记筛选内置顶；**有笔记禁删**（service 事务内检查，409 `book_has_notes`）；笔记文件落盘 `data/reading_notes/<book_id>/`，库中存相对路径与元数据，上传校验扩展名/大小/文件头签名，下载按库中路径解析（不接受用户传入路径，防穿越）。
- 右栏：`/api/infos`（important_infos 表）与 `/api/memos`（memos 表）——均为 CRUD + reorder，标题/内容完整显示自动换行（共用 RecordCard 组件），SafeMarkdown 先转义再解析（标题/列表/代码块/粗斜体/行内代码，链接仅 http/https），XSS 安全；长期保留不参与清理。
- **双向转换（移动语义，单事务原子）**：`POST /api/memos/{id}/to_task {target_date, task_type, is_important}`（标题/内容迁入 daily_tasks.content，删原备忘）；`POST /api/tasks/{id}/to_memo`（仅未完成，409 `task_done_not_convertible`；标题/内容迁入 memos，删原任务）。源记录删除使重复请求自然 404。
- 旧备忘文件：启动钩子调用 `migrate_legacy_memo()` 把 `~/.personal-hub/memo.md` 内容（如有）以固定标题导入一条备忘（幂等判重，不删除/不改写原文件）；memo.md 不再是数据源。
- 后台任务状态查询统一在 `/api/jobs/{id}`（与每日任务 `/api/tasks/*` 区分）。

### 3.4 清理审核模块（D4，已实现，迁移 0008）

`app/cleanup/`：protection（`protected_dates` 配置，Asia/Shanghai 口径，最高优先级）→ ensure_review（周日触发/错过补发，week_id 幂等，不覆盖未处理周期）→ generate_candidates（只读扫描两库 + Chroma，按群+日期分组，跨周 ref 去重）→ confirm（复检保护/一致性，生成删除计划明细落库）→ execute（TaskRunner kind `cleanup.execute`：validate → 归一化 → Chroma → 快照 → rag_state 回写 → done；单组失败不扩大范围，断点续跑，重试幂等）。

- 新表：`cleanup_reviews / cleanup_candidates / cleanup_delete_items / cleanup_audit`（hub.db，审计不存正文）。
- Chroma 保守策略：解析 `msg_ids` → 归一化时间戳逐条判定（不信 metadata.date）；全命中才删，混合/含保护/未知一律保留并记录原因；不做部分重建、零重新 Embedding；保留 chunk 可检索到已删文本在预览与结果中明示。
- rag_state 以实际剩余数回写（归一化 count + Chroma count），与 `incremental_index` 的"总数减少才全量重建"判定兼容（有负面对照测试证明必要性）。
- 互斥与重启安全：cleanup ↔ wechat.sync 双向 409；同 kind 409；启动钩子把遗留 pending/running 任务标记 failed（僵尸任务不永久阻塞，不依赖进程内锁）。
- 无任何自动删除入口；未确认执行 409；候选/预览零副作用。

### 3.5 GitHub 数据集成（阶段一，迁移 0010）

`app/adapters/github_source.py`（REST 客户端：Bearer Token 仅进程内持有；429/限流 403 按 Retry-After/Reset 等待重试最多 2 次；per_page=100 自动翻页）→ `app/services/github_service.py`（同步任务体，TaskRunner kind `github.sync`，同 kind 409 防重）→ `app/services/github_contrib.py`（贡献统计）→ `app/api/github.py`（`/status` / `/sync` / `/contributions?year=` / `/contributions/{date}`）。

- **存储**：`github_repos / github_commits / github_pull_requests / github_issues` 四表；主键取 GitHub 天然标识（repo id / sha / PR id / Issue id），`session.merge` 幂等；时间存 UTC ISO8601 文本，归属日由统计层转 Asia/Shanghai。
- **增量**：复用 `sync_cursors`（scope=`github:{full_name}`，epoch 秒）；commits 用 `since`（作者时间口径），PR/Issue 的 `since` 作用于 updated_at（会带回旧记录，幂等吸收）；逐仓库提交，失败已完成的仓库保留。
- **口径**：issues 端点混含的 PR（`pull_request` 键）不计入 Issue；第一版不同步 Events（避免重复计数）；已删仓库保守保留。
- **贡献统计（非 GitHub 官方口径）**：日贡献 = +08:00 当日 commit 数 + 新建 PR 数 + 新建 Issue 数；颜色等级固定阈值 1-2/3-5/6-8/≥9；覆盖范围取三类数据 min/max，未同步年份与零贡献明确区分（前端提示）。

### 3.6 启动器

`launcher/launch.py`：请求 `/api/health` 通则直接开浏览器；否则启动 uvicorn（隐藏窗口 .vbs）→ 轮询健康检查（超时 30s 报错）→ 打开浏览器。默认端口 8620（避开 WeChatDataAnalysis 的 10392）。`.bat/.vbs/.ini` 文件必须纯 ASCII（AGENTS §5）。

## 4. API 与接口约定

- REST-ish：`/api/<模块>/<资源>`；JSON 出入参，字段 snake_case 全项目统一。
- 错误统一 `{detail: {code, message}}`；HTTP 状态语义化（404/409/422/5xx）。
- 长任务：POST 返回 task_id，`GET /api/jobs/{id}` 查状态；问答 SSE（sse-starlette），会话经 session_id。
- 不加 `/v1` 前缀，破坏性变更时再引入。

## 5. 数据存储设计

- **hub.db**（SQLAlchemy + Alembic，迁移即 Schema 权威，模型与迁移一一对应）：业务数据全部在此——计划/任务/书籍/笔记元数据/资讯缓存/会话/任务/审计/token_usage/重要信息/随手备忘等。Schema 变更必须走 Alembic，先在隔离副本验证再应用真实库。
- **聊天两库**（`GetWechatInfo/DataInfo/` 快照库 + 归一化库）：沿用现有 Schema，不走 Alembic、不改表结构；应用侧只读（`mode=ro`）；原始快照层幂等 upsert 由同步流程负责。
- **Chroma**：沿用现有 `chat_chunks`（chunk_id = sha1(chat_id|msg_ids) 确定性 ID，metadata 含 msg_ids 逗号拼接字符串——where 不支持子串匹配，删除场景需客户端过滤）与 `rag_state`；不新增 collection 则不改名。
- 时间戳：业务库用 ISO8601 文本（本地时区）；聊天库沿用 epoch，服务层负责转换。
- 密钥：`~/.personal-hub/.env` 为权威（`PH_USER_ENV_DIR` 可覆盖），项目根 `.env` 可选覆盖；任何提交不得含密钥。
- 运行时数据（data/）不入 Git；旧备忘文件 memo.md 属用户私人内容不入 Git；`Output/` 历史报告兼容保留（D8）。

## 6. 横切设计

- **日志**：模块级 logging，按天滚动 `data/logs/hub.log`；文件日志只记时间/任务 ID/操作类型/数量/结果/耗时/非敏感错误摘要；聊天正文、Agent 完整回答、密钥不进文件日志。
- **异常**：服务层抛领域异常（DomainError 体系），API 层统一映射；外部调用全部设超时 + 最多 2 次指数退避重试；任务执行器捕获一切异常落任务表，不静默死亡。
- **Token 成本**：统一经 `llm_config.build_llm` 出口；每次 LLM/Embedding 调用写 `token_usage`（kind/model/input/output/ref）。

## 7. V2.0 演进约束（不提前实现）

局域网访问（0.0.0.0 + Bearer Token）→ HTTPS 反代 → 移动端同步（服务器为唯一写者 + 移动端纯 API 客户端）；备份恢复（D1）与同步服务一并设计。具体形态待 V2.0 评估；当前纯 API 设计已满足复用前提。

## 7.1 下一阶段演进方向（仅规划，未实现）

规划见 `DEVELOPMENT_PLAN.md`：GitHub 数据集成（官方 REST API，已确定不引入 GitHub MCP）、每日工作简报、长期记忆与跨数据源分析、Agent 执行追踪与效果评测、模型调用成本优化。落地时应遵循本文档分层约定（新业务入 services/、外部数据源入 adapters/、长任务走 tasks/ 状态机、LLM 出口统一 `llm_config.build_llm` 并落 `token_usage`），并在实现时补充本文件相应章节，当前不代表已实现。

## 8. 部署形态

单个 Windows 目录 + 桌面快捷方式；源码运行 `uvicorn --factory app.main:create_app` + 已构建 `web/dist`；默认端口 8620。


## 9. 晨报资讯候选采集（2026-11-11 更新）

`app/morning_report/adapters/` 获取中新网国内、国际页面的 `hotlist` 官方热点排行，各只检查前 10 篇详情，保留原始排名、标题、发布时间和来源摘录。榜单没有公开点击数、算法或更新时间，不能声称量化热度；国内、国际不按文章发布时间过滤，未知时间也可进入正文并标注“未知”；时间字段保留原始证据用于展示。同事件合并、不从第 11 条或其他来源补位。生产不再调用新浪、归档或热摸爽。

采集策略 `cnn_official_hot10_v3_ai_daily` 延续 AIHOT 日报字段与复用机制，并使旧国内/国际采集失效；不修改 Schema、不删除历史。正文三类资讯均确定性组装，国内/国际与 AI 各用独立占位符注入，完成后再评价和发布。

### 9.0 个人决策工作流

资讯整理和个人数据准备不调用模型。每日仅两个推理 Subagent：GoalAnalysis → ActionSuggest，然后主编 → 七维质量评价 → 发布。TechResearch 的每日节点、提示词、状态和依赖已移除；通用 RAG、技术资料及历史向量保留。

`PH_MR_PERSONAL_DB_PATH` 指向已核对的正式个人助手数据库，本机默认 `E:/wechat-LangGraph/data/hub.db`（8620 主进程使用的 main 配置）。`hub_readonly.readonly_connection` 强制 SQLite URI `mode=ro` 和 `query_only`，不存在时明确降级，不创建或回退到 V2 空库。记录数据源摘要标识、查询时间、各表数量、缺表及错误类型，不记录私人正文。任务、计划、重要信息、备忘和阅读元数据进入完整决策上下文；附件只读元数据，不声称读过正文。

Runner 将当前个人数据快照内的只读工具传给 `create_agent`：GoalAnalysis 使用 `search_personal_records`，ActionSuggest 使用 `search_personal_records` 与 `search_task_status`。不传入 RAG、历史数据库会话或历史索引配置，不提供历史晨报/建议工具。两个 Agent 的 prompt 和有效证据集均排除新闻；ActionSuggest 额外读取 GoalAnalysis 结果。来源 ID 必须属于本轮个人记录，工具不能扩展到新闻或历史报告证据；来源校验不是事实真实性证明。

GoalAnalysis 输出事实/分析/未知及证据 ID，ActionSuggest 输出个人依据、优先级、下一步与前置条件；无依据的时间/收益清空，允许零条。普通进度仅记录数量、工具调用、结果数、耗时和错误类型。评价接收最终正文及结构化、检索证据，采用 `decision_score_v2` 七维评分；缺个人记录时个人分析、目标关联、行动价值为 null，综合分只对可评价维度等权四舍五入。历史五维版本不重算；评价失败不阻塞发布。

模型保持已有配置：正式主编按允许时段使用 DeepSeek，手动主编使用 DashScope；两个 Subagent 使用 DashScope，评价显式使用 `quality_eval_model`（默认 qwen3.7-plus），不误复用正式主编客户端。评价和 Subagent 均显式关闭 Thinking，模型与 Token 用量如实记录。

### 9.1 AI 资讯：AIHOT 最新日报（2026-11-11 起）

- 唯一生产入口 `GET https://aihot.news/api/v1/dailies/latest`；必须核对 `report.date == report_date`，日期不符、结构异常或 HTTP 失败按来源失败降级（记录覆盖缺口），不允许旧日报冒充当期，不静默回退旧 items 接口（`fetch_selected` 仅历史兼容保留）。
- 收录依据是"属于当期日报"而非逐条原文发布时间落入本地窗口：sections.items 按原分类顺序收集，之后接 flashes，highlights 中未出现的条目补入；lead/highlights 只做重点标记，不重复加条目，lead 无可验证链接时不凭标题构造链接。
- 展示链接优先 `links.original`，缺失时用有效 `links.aihot`；只接受 http/https。原文 `publishedAt` 有则存、无则空，禁止用日报日期伪造；日报归属窗口（`daily_window_*`）与原文发布时间分开记录在 `raw_ref`。
- 去重按规范化链接确定性进行；条目的 `display_order`、`section_label`、`daily_kind`、`aihot_url` 等元数据存 `news_items.raw_ref`。
- 生成侧：AI 标题列表不参与模型筛选、不受 AI 60 条输入截断影响；`report_service` 从本期快照按 `display_order` 组装 `ai_daily` 注入图状态，主编提示词只保留占位行 `{{AI_NEWS_LIST}}`，正文由程序注入全部标题与链接（占位符缺失时改写/插入 AI 小节，剔除模型自写列表行，杜绝虚构与重复小节），之后才进质量评价与发布。提示词版本升级使旧阶段缓存自动失效。


### 晨报助手与 Memory 停用（2026-11-11）

删除晨报 `api/assistant.py`、`api/memory.py` 路由及前端客户端/对话组件，不再导出对应请求 schema。生成服务不查询 memories，图状态、决策上下文和证据集合不再接收 Memory；既有个人上下文及决策工具保持只读。`models.Memory` 仅作为历史 Schema 兼容映射保留，不执行数据库迁移或清理。右栏进度占满可用高度；提示词版本升级防止旧行为缓存复用。

2026-11-11 晨报展示调整：主编通过独立 EDITOR_SYSTEM 接收分点表达规范，“我的昨日”一事一点，“今日建议”编号且包含依据和下一步。开篇速览在正文新闻列表组装后确定性注入，取国内/国际已选列表首条、当期 AI 日报首条及所有“技巧与观点”（兼容“讨论与观点”）条目，保留原始标题链接与摘要；缺项不虚构。组装后的最终正文统一进入质量评价和发布。前端速览摘要直接显示，正文摘要仍默认折叠。

2026-11-11 新闻星标：晨报独立 SQLite 轻量迁移 v4 为 `news_items` 新增 `is_important BOOLEAN NOT NULL DEFAULT 0`；服务 `news_importance` 按新闻 ID 更新，并按已有确定性 `content_hash` 同步重复采集记录，后续采集继承已标记状态。`GET /api/morning/report/{version_id}/news` 返回该报告所选新闻的当前状态；`PATCH /api/morning/news/{news_id}/importance` 接收严格布尔 `is_important`。报告快照不因用户星标改写，前端按原始新闻记录关联实时星标，速览与正文同步；无法关联的历史条目禁用星标。仅涉及晨报独立库，不改 hub.db 或聊天库。

2026-11-11 生成链路简化：历史检索与索引检查、修复、发布后向量更新已移除，不初始化 Qdrant 或 Embedding Provider。已有独立索引工具与向量数据仅保留兼容，不在生成中调用。进度移除 `index`，共 9 步；`snapshot` 仍显示“准备本轮数据”，保留新闻固定输入、snapshot_id 和部分个人事件证据。GoalAnalysis 与 ActionSuggest 只分析个人上下文，不输入新闻；新闻保留给正文组装、速览及质量评价。历史报告查看和版本记录不受影响。

晨报 LLM 输出契约（2026-11-11）：所有模型实际请求必须使用 JSON mode（`response_format={"type":"json_object"}`），包括两个 Subagent 的每轮工具循环、主编和质量评价。Subagent 请求通过 SDK `extra_body` 合并 response_format 到实际顶层 HTTP JSON，以保持原生工具协议、避免当前 LangChain 自动 strict-tool 解析限制。最终输出严格解析为 JSON 对象，不接受围栏、额外说明、非标准数值或重复键。目标/建议/评分保持既有 JSON 字段，主编返回非空字符串 `content_md`；验证和解包后再确定性组装新闻、评价与发布，数据库/API/前端继续使用 Markdown 正文。主编格式错误停止发布，分析与评价按已有策略显式降级，不静默消费纯文本。
