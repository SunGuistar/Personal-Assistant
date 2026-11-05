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

### 3.4 清理审核模块（D4，尚未实现）

设计已定（实现见 DEVELOPMENT_PLAN 阶段 5）：每周日生成候选（cleanup_candidates，item_type 仅微信两类消息；新闻不参与）→ 用户勾选 + 确认（cleanup_runs）→ 删除执行器逐项状态机（pending → normalized_deleted → chroma_done → snapshot_deleted → done/failed，可断点续跑）→ 审计（audit_log，不存内容）。无 confirmed run 执行器拒绝（409）；chunk 部分命中按剩余消息局部重建（新 chunk_id upsert + 删旧），执行器维护 rag_state 计数使后续增量索引不再全量重建；跨周候选去重（同一 ref_id 不重复出现在未完结审核中）。

### 3.5 启动器

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

## 8. 部署形态

单个 Windows 目录 + 桌面快捷方式；源码运行 `uvicorn --factory app.main:create_app` + 已构建 `web/dist`；默认端口 8620。
