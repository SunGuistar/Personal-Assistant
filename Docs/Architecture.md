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

- 长期计划与每日任务**完全独立**（迁移 0006 移除 plan_id，0 条历史关联）。排序统一为 **未完成优先 > 重要 > 任务类型（daily/feature_add/feature_optimize/idea，迁移 0007 新增 task_type 列，存量默认 daily）> sort_order**：计划 `PUT /plans/reorder`、任务 `PUT /tasks/reorder`（统一待办排序，ordered_ids 覆盖某日视图全部可见任务；分组序列被改变即 409 `reorder_cross_group`，前端在分组边界禁用按钮）均按位置写 sort_order。已完成任务置底（内部完成时间倒序）。完成可反复切换（取消完成清除 completed_at，移除原 history_readonly 限制）。"移至下一天" = 改 task_date + moved_from_date 溯源，不复制副本。
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

### 3.5 每周回顾模块（阶段一，迁移 0009）

`app/review_agent/`（LangGraph Agent，与 wechat_agent 同装配模式）+ `app/services/review_stats.py`（确定性周统计）+ `app/services/review_service.py`（草稿/建议/确认状态机）+ `app/api/reviews.py`（SSE 路由）。只读分析 + 人工确认，Agent 无任何写工具。

- **统计口径**（`review_stats`）：自然周周一至周日，任意日期归一化到所在周周一；完成周看 `completed_at`（NULL 不计）、归属周看 `task_date`；周末逾期 = 周日快照（`task_date <= 周日` 且未完成或晚于周日完成，含历史积压）；默认周期为上一个完整自然周。
- **Agent**：`create_agent` 单 Agent + 六个只读工具（任务统计/任务明细/计划/备忘/重要信息/阅读，工厂绑定 Session 与周期）；系统提示词注入本机日期与周期；LLM 经 `build_llm(temperature=0.2, stream_usage=True)`（stream_usage 使流式响应回传真实 token 用量）。
- **建议生成**：独立结构化调用（JSON Mode），上下文 = 对话历史 + `stats_json` 快照 + 重新读取的业务事实 + 用户补充；basis 逐条经 `validate_basis` 校验（记录存在 + 理由非空 + daily_task 须与周期有交集），通过者回填 `fact` 事实摘要，无效剔除（basis 空数组 = 一般性建议）；生成并发由 per-review 非阻塞锁保证（409）；已处置建议禁止重生成覆盖；失败不破坏已有草稿。
- **状态机**：`weekly_reviews` draft → confirmed（单向；`ux_weekly_reviews_confirmed_week` 部分唯一索引保证同周仅一份正式周报，IntegrityError → 409）；`weekly_review_suggestions` pending → accepted/modified/rejected；确认前正文（analysis_md/user_notes）可编辑，确认时由确定性代码组装 `report_md`（统计 + 分析 + 补充 + 已处置建议，拒绝项留痕）。
- **对话持久化**：`weekly_review_messages`（刷新可恢复）；SSE 事件协议与微信问答一致（token/done/error，建议生成另有 step 事件）；LLM 用量经 `llm_usage` 落 `token_usage`（`weekly_review:chat:{id}` / `weekly_review:suggest:{id}`）。
- 第一版不接微信与资讯数据；不用 Chroma 存周报；周报长期保留不参与清理。

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

规划见 `DEVELOPMENT_PLAN.md`：每周回顾 Agent、每日工作简报、跨数据源检索与长期记忆、GitHub 数据集成、模型调用成本优化、执行追踪与效果评测。落地时应遵循本文档分层约定（新业务入 services/、外部数据源入 adapters/、长任务走 tasks/ 状态机、LLM 出口统一 `llm_config.build_llm` 并落 `token_usage`），并在实现时补充本文件相应章节，当前不代表已实现。

## 8. 部署形态

单个 Windows 目录 + 桌面快捷方式；源码运行 `uvicorn --factory app.main:create_app` + 已构建 `web/dist`；默认端口 8620。
