# AGENTS.md — Personal Hub 开发规范

本文件约束所有在本仓库工作的开发者与 AI 编码助手。规划类文档见 `Docs/`（PRD=V1.0 需求、ARCHITECTURE=设计约束、DEVELOPMENT_PLAN=V1.0 任务、TEST_PLAN=测试、**ROADMAP=V1.0 之后规划的唯一权威来源**）；`wechat-chat-summary/` 是独立上游项目（已被 .gitignore 忽略），不适用本规范。

## 1. 仓库定位与现状

- 主项目：基于 LangGraph 的微信聊天 Agent（已能运行），正在扩展为 Personal Hub（FastAPI + React 个人管家）。
- 现有微信链路：`GetWechatInfo/`（API 客户端 + 原始快照库）→ `Tool/structured_message.py`（归一化）→ 归一化 SQLite + Chroma 向量 → `LangGraph/`（Agent 工具 + 总结流水线）。
- 已知问题（修改相关代码前必读）：
  1. `normalize_snapshot.py` 被多个模块引用但**源码缺失**，按 DEVELOPMENT_PLAN 阶段 3.4 重建（迁移后建于 `app/wechat_agent/` 内）。
  2. `LangGraph/` 目录名与 pip 包 `langgraph` 冲突。**D3 已批准**：阶段 3 按"回归测试→目录迁移→验证→其他改造"的顺序迁入 `app/wechat_agent/`，不再征求意见；此前 `app/` 新代码一律不得 import 该目录。
  3. Agent 工具的 docstring 就是提示词，**改 docstring = 改模型行为**，任何修改须先在 TEST_PLAN 框架内验证。
  4. 聊天相关 SQLite 一律 `mode=ro` 打开，Agent 层只读是硬约束。
- 常驻决策（不必再问）：总结统一经 Agent（见 §4.7）；第一版无备份功能，以 §5 数据隔离规范替代（D1）；允许自动启动设置中配置的 WeChatDataAnalysis（D5）。

## 2. 目标目录结构（新代码遵循）

```
app/            FastAPI 后端（api 路由 / services 业务 / adapters 外部适配 / wechat_agent 微信模块 / models / tasks / cleanup）
web/            React + TS + Vite 前端
launcher/       Windows 启动器
data/           运行时数据（hub.db、logs/、reading_notes/），新增运行时数据禁止入库
tests/          pytest
LangGraph/ GetWechatInfo/ Tool/   现有微信模块（阶段 3 迁入 app/wechat_agent/ 后删除原目录）
Docs/           规划与架构文档
```

## 3. 命名规范

- 文件/目录：snake_case；Python 类 PascalCase；函数与变量 snake_case；常量 UPPER_SNAKE。前端组件 PascalCase.tsx，hooks/useXxx.ts。
- 数据库：表 snake_case 复数（daily_tasks、news_items）；字段 snake_case；主键 `id`；时间统一 `created_at/updated_at`（ISO8601 文本）；枚举用短字符串（todo/reading/done）。**Schema 管理范围**：hub.db 全部新表走 Alembic；聊天两库沿用现有 Schema、不走 Alembic、不改表结构。
- Chroma：Collection 名 snake_case（现有 `chat_chunks`、`rag_state` 不得改名）；文档 ID 规则=确定性哈希（现有 chunk_id = sha1(chat_id|msg_ids)），**禁止随机 UUID 作为幂等键**；metadata 键 snake_case。
- API：`/api/<模块>/<资源>`；请求/响应字段全项目统一 snake_case（前端直接消费）。
- 状态枚举：`tasks.status` 统一 pending/running/success/failed；清理逐项中态（normalized_deleted 等）以 ARCH §3.4 状态机为准，不适用四态约束。

## 4. 架构铁律

1. 前后端彻底分离：前端只调 `/api/*`，禁止前端直连数据库、执行系统命令。
2. 业务逻辑写在 `services/`，路由层只做校验与序列化；`services/` 不得 import FastAPI 对象（可单测）。
3. 外部系统（WeChatDataAnalysis、HN、RSS、GitHub）一律经 `adapters/` 封装，服务层不得直接发 HTTP。
4. 长任务（总结、同步、索引、清理执行）必须走 `tasks/` 状态机，禁止在请求线程里跑长任务。
5. 不引入微服务/消息队列/常驻守护进程；不新增未经讨论的重依赖。
6. 复用优先：微信检索/总结/向量逻辑零重写，只做接口适配。
7. **总结统一经 Agent（D2）**：所有总结请求（含快捷按钮）必须进入 Agent 由 `summarize_chat` 工具触发；**禁止**建立 Service 直调 `run_summary` 的旁路通道；Service 只做调用封装、任务状态与报告管理。
8. **禁止自动删除**：任何数据删除必须经清理审核流程人工勾选 + 确认；系统不得存在自动删除入口。
9. **未来需求不进当前计划**：未来需求统一维护在 `Docs/ROADMAP.md`；未经用户明确批准，不得将其加入当前版本开发计划（DEVELOPMENT_PLAN.md）或提前实现。

## 5. 数据与安全

- **数据隔离铁律（D1 配套，最高优先级）**：开发、调试、迁移验证、破坏性测试一律使用隔离副本或临时库；测试代码禁止出现真实聊天库/Chroma 真实目录的写路径（测试计划含"数据隔离守卫"用例）。对唯一真实聊天库执行任何**不可逆操作前，必须先向用户说明风险并获得批准**。
- 第一版不实现备份/恢复系统（D1，已规划为 V2.0，见 `Docs/ROADMAP.md`）；未经用户批准，不得把备份或其他 ROADMAP 中的未来需求加回当前开发范围。
- hub.db 的 Schema 变更必须走 Alembic，迁移脚本在隔离副本验证通过后才应用于真实库。
- 敏感配置（API Key）**权威文件位于用户目录 `~/.personal-hub/.env`**（仓库之外，防项目目录变动丢失）；项目根 `.env` 仅作可选本地覆盖（项目 .env > 用户目录 .env）；键名清单见项目根 `.env.example`（可提交）。统一经 `env_bootstrap.load_hub_env()` 加载（app/config.py 与微信模块均已接入），用户目录可用环境变量 `PH_USER_ENV_DIR` 覆盖。代码只经 `os.environ`/pydantic-settings 读取；**任何提交不得包含密钥**。
- 审计日志只记元数据（数量、类型、结果），不记聊天内容原文。
- 禁止读写 WeChatDataAnalysis 管理的原始微信数据库；聊天快照/归一化库是本项目唯一可管理的微信数据。
- 现有 `Output/` 历史报告与问答文件：兼容保留，未经用户确认不得清理或删除（D8）。

## 6. 日志与异常

- 新代码用 `logging`（模块级 logger），禁止裸 `print` 进新模块；按天滚动到 `data/logs/`。
- **文件日志隐私白名单**：只记录时间、任务 ID、操作类型、消息数量、执行结果、耗时、非敏感错误信息（类型与摘要）。**禁止**将聊天消息正文、Agent 完整回答、密钥转存到文件日志；含正文的内容只允许存在于对话存储（chat_messages）与报告产物。收敛现有 print 时按此规则区分处理，不改业务行为。
- 外部调用必须设超时；重试最多 2 次、指数退避；禁止无限重试与裸 `except:`。
- 服务层抛领域异常，API 层统一映射为 `{detail:{code,message}}`；后台任务异常必须落任务表，禁止静默吞掉。
- **Windows 脚本与 ini 配置必须纯 ASCII**：`.bat` / `.vbs` / `.cmd` / `.ini` 文件不得包含任何非 ASCII 字符（中文注释也不行）。cmd/VBScript 按系统 ANSI 代码页（GBK）读取文件，UTF-8 中文字节会导致引号错位、报错位置漂移（如 800A0005"无效的过程调用"）或 BOM 直接报"无效字符"；中文说明写在配套 `.md` 或相邻 Python 文件的 docstring 中。

## 7. 测试要求

- 每阶段出口标准 = 该阶段测试全绿（详见 `Docs/TEST_PLAN.md`）。
- LLM/Embedding/外网一律 Mock（fake LLM、respx、fixture 文件），默认测试零付费、零外网、零真实生产数据。
- **目录迁移必须回归对拍**：迁移前后同一组基线测试（Agent 工具输出、总结报告 Schema、检索结果）均绿且一致（D3）。
- 修 bug 先写复现测试；禁止删失败测试、禁止给断言放水。

## 8. 修改现有功能的流程

改动 `LangGraph/`（或迁移后的 `app/wechat_agent/`）任何行为前必须：
1. 写明影响面（哪个工具/流水线/提示词受影响）；
2. 跑现有冒烟：单轮问答 + 单日总结（用已有库数据，断言报告结构）；
3. 多群/迁移相关改动需对拍历史输出。

## 9. 成本控制

- 非 AI 功能禁调 LLM；统计问题优先 SQL；消息同步增量；向量不重复构建；已有总结数据未变化时复用。
- 每次 LLM/Embedding 调用经统一出口写入 `token_usage` 表。

## 10. 提交规范

- commit message 用中文简述变更意图；阶段节点打 tag（stage-N）。
- 文档与代码同 PR 更新（改了行为就改对应 Docs/AGENTS.md）。
