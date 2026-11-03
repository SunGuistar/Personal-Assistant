# Personal Hub 架构设计文档

版本：v0.2（已含用户决策 D1–D8）
配套文档：`PRD.md`（需求）、`DEVELOPMENT_PLAN.md`（计划）、`TEST_PLAN.md`（测试）

## 1. 总体架构

```
┌──────────────────────────────────────────────────────────┐
│ 浏览器 (React SPA, 构建产物由 FastAPI 托管)                  │
│  首页/微信/资讯/计划/阅读/清理审核/设置                       │
└──────────────────┬───────────────────────────────────────┘
                   │ HTTP /api/* (JSON, 127.0.0.1:8620)
┌──────────────────▼───────────────────────────────────────┐
│ FastAPI 应用 (app/)                                        │
│  api/ 路由层 → services/ 业务层 → adapters/ 外部适配层       │
│  tasks/ 后台任务(状态机)   cleanup/ 清理审核                │
│  models/ SQLAlchemy   db.py engine+迁移(Alembic)           │
└───┬──────────┬──────────────┬──────────────┬──────────────┘
    │          │              │              │
 SQLite     Chroma      微信模块(阶段3迁入     外部源
 hub.db   (复用现有    app/wechat_agent/)      WeChatDataAnalysis
(业务数据)  VectorStore)                      HN/RSS/GitHub API
```

原则：前后端彻底分离；业务逻辑集中在后端服务层；外部系统一律经适配器；长任务异步化。

## 2. 目标目录结构

```
app/                  # FastAPI 后端包（personal_hub 核心）
├── main.py           # 应用装配：中间件、路由、静态资源、启动钩子
├── config.py         # pydantic-settings：端口(默认8620)、路径、更新间隔、模型、来源配置
├── db.py             # engine、session、Alembic 环境
├── api/              # 路由薄层：参数校验(in schema) → 调 service → 出 schema
│   ├── dashboard.py  ├── wechat.py  ├── news.py
│   ├── plans.py      ├── reading.py ├── cleanup.py  └── settings.py
├── services/         # 纯业务逻辑，不依赖 FastAPI 对象（可单测）
├── adapters/         # wechat_api(复用现有client) / news_hn / news_rss / launcher
├── wechat_agent/     # 阶段 3 迁入：原 LangGraph/ GetWechatInfo/ Tool/（D3）
├── tasks/            # 任务注册、执行器、状态落库；进程内 asyncio 执行
├── cleanup/          # 候选生成、审核流程、三层删除状态机、chunk 局部重建、审计
└── static/           # React 构建产物（web/dist 拷贝或软链）
web/                  # React + TS + Vite 前端
launcher/             # launch.py（健康检查+拉起 uvicorn+开浏览器）+ .bat/.vbs
data/                 # 运行时数据（gitignore）：hub.db、logs/、reading_notes/
tests/                # pytest：单元 + 集成（Mock 外部 API 与 LLM）
Docs/                 # 本文档等
```

阶段 3 前，现有微信模块仍位于原路径（`LangGraph/`、`GetWechatInfo/`、`Tool/`），目录名与 pip 包 `langgraph` 存在大小写冲突隐患（Windows 下目前可运行，跨平台构建有风险），按 D3 在阶段 3 分步迁入 `app/wechat_agent/`（顺序见 DEVELOPMENT_PLAN，已批准不再征求意见）。

## 3. 模块边界与复用方案

### 3.1 微信模块（复用为主，适配为辅）

| 现有代码 | 复用方式 |
|---|---|
| `GetWechatInfo/wechat_data_api.py` | 直接实例化；适配器 `WechatSourceAdapter` 封装健康检查、会话解析、消息拉取、桌面程序启动（D5，仅启动设置中配置并校验的 exe） |
| `GetWechatInfo/message_store.py` | 作为原始快照层继续用；同步服务在其上编排 |
| `Tool/structured_message.py` | 归一化唯一实现，重建 normalize 脚本时直接调用 |
| `LangGraph/Chat_tools/*`（8 工具 + summarizer） | **整体原样挂入 Agent（D2）**：所有总结请求由 Agent 决策调用 `summarize_chat` 工具触发，禁止 Service 直调 `run_summary` 的旁路 |
| `LangGraph/Normal_Tools/rag_store.py` | 增量索引导出为 service 方法；检索逻辑零改动；删除场景配合见 §3.4 |
| `LangGraph/llm_config.py` | 继续作为 LLM 唯一出口；设置页改 `llm_config.json` + 环境变量 |

**对话式交互（前端主形态）**：微信页主体为对话窗口——用户输入自然语言或点击 3 个预置快捷输入，均进入**同一个 Agent 流程**（无特殊通道）；群/日期/范围由对话指定（Agent 经 list_chats 解析群名，相对日期由系统提示词注入机制处理）；SSE 流式返回。Service 层职责仅限：Agent 调用封装（SSE 会话管理）、任务状态、报告产物收集与列表化、同步编排——**不替代 Agent 做任何总结决策**。总结在对话中内联显示执行状态，完成后回填报告卡片；同步按钮/数据范围/运行状态收进对话上方辅助区。后端对应 `POST /api/wechat/chat`（SSE，session_id 关联服务端会话历史）与 `GET /api/wechat/source/status`、`POST /api/wechat/sync`（任务化）。

**重建 `normalize_snapshot.py`**：从原始快照库读 `message_json`，经 `from_raw_rows` 归一化，幂等 upsert 进归一化库（PK: chat_id+message_id）。脚本在目录迁移（D3 第一步）完成后建于 `app/wechat_agent/` 内，与迁移同步修正所有引用它的报错文案。

**多群适配**：总结流水线的"单群限制"在服务层解决——总结请求必须显式携带 chat_id，service 按群过滤消息后再进流水线；Agent 系统提示词补充群选择约束。不改变流水线内部行为。

**同步流程（游标统一设计，`sync_cursors` 为唯一游标口径）**：

1. `GET /api/wechat/source/status` → 探测 WeChatDataAnalysis（读 `/api/chat/accounts`）。
2. 未运行 → launcher 适配器按配置路径启动桌面程序（D5）→ 轮询 API 就绪（超时返回明确错误）。
3. 读取 `sync_cursors`（scope=chat_id，字段 `last_timestamp` + `last_msg_id`），拉取 `(timestamp, message_id) > 游标` 的消息（成对比较，**避免同一秒多条消息漏拉**）；首次全量。
4. 原始行幂等 upsert（PK 冲突即跳过）→ 归一化（指纹去重）→ 更新游标（与消息写入同事务提交，**中断恢复不重复不遗漏**）。
5. 调用 `rag_store.incremental_index()`（chunk_id 确定性，天然幂等）。
6. **迟到历史消息对账**：同步完成后按日比对原始库与归一化库计数，差异区间重导该日范围（游标不后退，靠幂等兜底）。

### 3.2 资讯模块

```
news_sources 表配置源(默认种子见 PRD §2.2) → FeedFetcher(httpx, 超时/重试/UA)
→ 归一化为 NewsItem(title, url, source, published_at, raw_summary, heat_raw)
→ 去重(url 规范化+标题哈希) → 归一化热度(按来源函数) → 规则评分
→ news_items 落库 → 过期判定(7天,未收藏) → 清理候选
```

- 调度：应用启动时 + 运行中每 N 分钟（可配，默认 30）检查一次新鲜度；应用关闭不运行（不驻留）。
- 评分：`score = norm_heat(source, heat_raw) * source_weight * age_decay(published_at)`；各来源 `norm_heat` 为独立纯函数，单元测试覆盖。
- LLM 不参与新闻链路。

### 3.3 计划与阅读模块

标准 CRUD 服务：long_term_plans → daily_tasks（plan_id 可空，sort_order 手动排序，**"移至下一天"= 更新 task_date + 记录 moved_from_date**，不复制副本）；books / book_notes（文件落盘 `data/reading_notes/<book_id>/`，库中存路径与元数据，上传校验扩展名与大小，PDF/PNG 浏览器直开）。

### 3.4 清理审核模块（三层状态机，D4）

```
[周日/下次启动] 生成器扫描过期数据 → cleanup_candidates
  (week_id, item_type, ref_id, description, date_range, size_estimate, state)
  · item_type: normalized_msgs / snapshot_msgs / news_items
  · 微信消息候选按"同一天地三库关联"归为一个候选项，一次勾选三层同删
        │
  用户在审核页勾选 → cleanup_runs(week_id, confirmed_at)  ← 无 confirmed run，执行器拒绝执行
        │
  删除执行器（可重试、断点续跑；仅由确认的 run 触发）：
  每项: pending → normalized_deleted → chroma_done → snapshot_deleted → done
                        │任一步失败→ failed(记录原因, 可重跑；重跑对已删步骤幂等)
        │
  audit_log(run_id, item_type, count, status, error, created_at)   ← 不存内容
```

- **微信消息三层删除顺序**：归一化库（按 message_id 列表删）→ Chroma chunk 处理 → 原始快照库删对应 `message_json` 行。不动 WeChatDataAnalysis 原始库；不误删总结报告。
- **Chroma chunk 处理策略（针对 `rag_store.py` 实际实现设计，避免全群重建）**：
  1. 识别受影响 chunk：按 `chat_id` + `date` 元数据 where 取回候选文档后**客户端过滤**——现有 metadata 中 `msg_ids` 是逗号拼接字符串，Chroma where 不支持子串匹配，无法直接按消息 ID 服务端过滤。
  2. chunk 的消息全部在删除集内 → 直接删除该文档；
  3. 部分命中 → 用剩余消息按现有 `chunk_messages` 规则重建（消息集合变化 → 新 chunk_id → upsert 新文档 + 删除旧文档）。**Embedding 成本仅限重建的少数 chunk，未变化 chunk 的向量全部复用**；
  4. 删除执行器维护 `rag_state` 计数（total_msgs、chunk_count），使后续 `incremental_index()` 因计数一致而**不再触发全群全量重建**；
  5. 保证：已删除消息不再出现在任何 chunk 文本中，语义检索检索不到。
- **跨周候选规则**：候选按 week_id 归属；生成新一周候选时，跳过仍挂在未完结审核（未确认、未执行）中的同一 ref_id，避免同一数据同时出现在两个审核清单；用户跳过时勾选状态保留，下周不重复生成同一 ref_id；已执行完毕的审核归档留存。
- **非授权删除防护**：候选生成器只读；执行器校验 run 已确认否则拒绝（409）；系统中不存在任何自动删除入口。
- 新闻删除：单表单删，无关联。
- 以上能力与对应测试在阶段 5 正式开放删除前完成（DEVELOPMENT_PLAN 阶段 5）。

### 3.5 启动器

`launcher/launch.py`：`请求 http://127.0.0.1:8620/api/health` → 通则直接开浏览器；否则启动 `uvicorn app.main:app`（隐藏窗口 .vbs）→ 轮询健康检查（超时 30s 报错）→ `webbrowser.open`。桌面快捷方式指向 .bat。服务默认端口 **8620**（避开 WeChatDataAnalysis 的 10392），可在设置中修改。

## 4. API 设计约定

- 风格：REST-ish，`/api/<模块>/<资源>`，JSON 出入参，字段 snake_case 全项目统一；列表统一 `{items, total, page?}`。
- 错误：统一 `{detail: {code, message}}`；HTTP 状态语义化（409 冲突/未确认清理 run、422 参数、502 外部源失败、504 外部超时）。
- 长任务：POST 返回 `task_id`；`GET /api/tasks/{id}` 返回 `{status, progress, error, result}`；问答流式用 SSE（`sse-starlette`），会话经 `session_id`。
- 版本：第一版不加 `/v1` 前缀，破坏性变更时再引入。

## 5. 数据模型与命名规范

### 5.1 应用库 `data/hub.db`（SQLAlchemy + Alembic）

通用字段：`id INTEGER PK AUTOINCREMENT`、`created_at`、`updated_at`（ISO8601 文本，本地时区）。

| 表 | 关键字段 |
|---|---|
| `long_term_plans` | title, description, status, target_date |
| `daily_tasks` | plan_id→long_term_plans NULL, task_date, title, done, sort_order, moved_from_date NULL |
| `books` | title, author, note, status(todo/reading/done) |
| `book_notes` | book_id→books, filename, path, size, uploaded_at |
| `news_items` | title, url UNIQUE(规范化), source, published_at, raw_summary, norm_heat, score, is_favorite, is_read, fetched_at |
| `news_sources` | name, kind(rss/hn/github), endpoint, enabled, weight（默认种子见 PRD §2.2） |
| `sync_cursors` | scope(chat_id) PK, last_timestamp, last_msg_id, updated_at |
| `chat_sessions` | id, title, created_at, updated_at（微信对话会话） |
| `chat_messages` | session_id→chat_sessions, role(user/assistant), content, created_at（会话级历史，支撑多轮上下文） |
| `tasks` | kind, status, progress, payload_json, result_json, error |
| `cleanup_candidates` | week_id, item_type, ref_id, description, date_range, size_estimate, state |
| `cleanup_runs` | week_id, confirmed_at, status |
| `audit_log` | run_id, item_type, count, status, error |
| `token_usage` | kind(llm/embedding), model, input_tokens, output_tokens, cost_estimate, ref |

命名：表/字段 snake_case；`tasks.status` 统一 pending/running/success/failed；cleanup 逐项中态（normalized_deleted 等）见 §3.4，不受四态约束；时间戳存储 INTEGER(epoch) 或 ISO 文本（聊天库沿用 epoch，业务库用 ISO 文本，服务层负责转换）。

### 5.2 Chroma（沿用现有）

- `chat_chunks`：文档=chunk 文本，metadata={chat_id, date, start_ts, end_ts, msg_ids(逗号拼接字符串), senders, content_hash}；ID=chunk_id（sha1(chat_id|msg_ids)，确定性）。
- `rag_state`：每群一条进度记录（删除场景由清理执行器维护，见 §3.4）。
- 不新增 collection 则不动现有命名；删除按现有 metadata 过滤 + 客户端过滤（限制见 §3.4）。

### 5.3 与现有库的关系

- 聊天数据保留现有两库（raw snapshot + normalized），应用库只存游标/会话/任务/审计等管理数据。
- hub.db 的 Schema 变更必须走 Alembic，且在隔离副本上验证迁移脚本后再应用于真实库（PRD §2.6）；聊天两库沿用现有 Schema，不走 Alembic。
- 按 D1，第一版无备份功能：对真实聊天库的任何写路径在合并前必须能用隔离副本全量回放验证；不可逆操作执行前需用户批准。

## 6. 横切设计

### 日志（隐私白名单）

- `logging` + 按天滚动文件 `data/logs/hub.log`。**文件日志只保存**：时间、任务 ID、操作类型、消息数量、执行结果、耗时、非敏感错误信息（错误类型与摘要，不含堆栈中的正文）。
- **禁止**将聊天消息正文、Agent 完整回答、密钥等敏感内容从 print 机械转存到文件日志（阶段 3 收敛 print 时按此规则区分处理，不改业务行为）；含正文的内容只允许出现在对话存储（chat_messages）与报告产物中。
- 适配器层记录外部请求（URL、耗时、状态码）。

### 异常

- 服务层抛领域异常（SourceUnavailable、SyncConflict、CleanupError…），API 层统一映射；外部调用全部设超时 + 有限重试（指数退避，最多 2 次）。
- 任务执行器捕获一切异常落任务表，不让后台任务静默死亡。

### 备份与恢复（D1：第一版不实现，V2.0 已确定需求，仅保留设计约束）

- 未来方案（V2.0 建设，权威规划见 `Docs/ROADMAP.md`）：SQLite online backup（`con.backup()`）导出 hub.db + 聊天两库 + Chroma 目录打包；恢复为离线操作（停服务→解包→校验→启动）。
- 第一版替代保障 = PRD §2.6 数据操作安全规范（隔离副本 + 危险操作审批）。

### Token 成本

- 统一经 `llm_config.build_llm` 出口，包装记录 usage 到 `token_usage`；设置页展示累计与估算费用；Embedding 调用已有统计，接入同一表。

## 7. 未来移动端演进（V2.0，仅保留设计约束）

> 权威规划见 `Docs/ROADMAP.md`；本节仅保留 V1.0 必须遵守的设计约束，不提前实现。具体形态（PWA / 手机浏览器访问 / 独立 App）待 V2.0 启动时评估。

1. 阶段一（已有）：API-first、响应式 Web、127.0.0.1:8620。
2. 局域网访问：绑定 `0.0.0.0` + 简单 Bearer Token（settings 生成），HTTP 仅限内网。
3. 安全远程：HTTPS（Caddy/nginx 反代或自签证书）+ 认证强化。
4. 数据同步：SQLite 单写者限制下，移动端采用"服务器为唯一写者 + 移动端纯 API 客户端"；离线场景后续评估增量同步服务。第一版的纯 API 设计已满足复用前提。
5. **备份与恢复系统**：V2.0 已确定需求（D1），与同步服务一并设计，权威规划见 `ROADMAP.md`。

## 8. 测试、部署形态

- 后端 pytest（单元/集成，Mock LLM 与外部 API，隔离数据副本）；前端 Vitest + RTL（组件级）；端到端关键路径手工 + 可选 Playwright。
- 交付物：单个 Windows 目录 + 桌面快捷方式；源码运行 `uvicorn app.main:app` + 已构建 `web/dist`；默认端口 8620。
- 详见 `TEST_PLAN.md`。
