# AGENTS.md — 个人助手开发规范

## 项目与文档入口

本规范适用于本仓库。独立上游项目 `wechat-chat-summary/` 除外。个人助手是仅面向 Windows PC 的 FastAPI + React 应用，默认访问 `127.0.0.1:8620`。本地开发使用 Conda `agent`（Python 3.13），前端依赖与构建命令见 README。

**涉及今日晨报的任务，无论改动位于后端、前端、测试还是公共接口，都先阅读[晨报开发规范](app/morning_report/AGENTS.md)及其指向的必要文档。**

- 启动与使用见 [README](README.md)。按当前代码查找模块与入口时，读[系统架构地图](ARCHITECTURE.md)。
- 现行业务规则的权威来源为[产品需求](Docs/PRD.md)，技术架构与设计的权威来源为[技术架构](Docs/Architecture.md)。发现文档与实现不一致时，说明差异并向用户确认涉及行为或权限的变更。
- 既有阶段和后续功能范围见[开发规划](Docs/DEVELOPMENT_PLAN.md)。[仓库计划](Docs/PLANS.md)、[产品规格索引](Docs/product-specs/index.md)和[设计文档索引](Docs/design-docs/index.md)目前是预留入口。晨报专项的实际计划由模块规范导航。

## 文档维护与执行计划

- **持续同步。** 业务需求、架构、接口、技术设计、功能规划、开发规范或验收要求发生实质变化时，核对事实并更新对应文档。同一信息由职责对应的文档维护，其他文档优先引用。各级 `ARCHITECTURE.md` 记录当前实际架构，Design Docs 记录拟采用的设计。方案实施后，再按实际结果更新架构地图。
- 实施中发现代码与文档不一致时，先核实原因并及时处理，必要的文档更新须在任务结束前完成。重要设计变更应说明原因。变更已确认的需求或验收标准须先获确认，不能为迁就实现而直接改写。普通代码调整若不影响文档准确性，无须更新文档。
- 不另设 `TEST_PLAN.md`、`ROADMAP.md` 或 `CHANGELOG.md`。重大技术决策先说明理由和备选方案，再建议是否记入 [ADR](Docs/ADR/)。普通 UI 调整和小型重构无需 ADR。
- **ExecPlan（执行计划）。** 复杂功能、重大架构调整或跨多个步骤的长期任务应使用 ExecPlan，简单修改无须强制创建。采用五阶段流程时，通常在阶段三建立。仓库 `Docs/PLANS.md` 用于总体规划与固定任务范围，晨报专项范围见[晨报计划](app/morning_report/PLANS.md)。Product Specs 定义需求和验收标准，Design Docs 提供技术方案与依据，ExecPlan 记录具体任务的实施步骤与过程，并引用相关规格和设计。
- 进行中的计划保存在 [`Docs/exec-plans/active/`](Docs/exec-plans/active/)。执行中持续记录进度、重要发现、关键决策及理由、验证结果和剩余工作。恢复任务时先读对应计划，从已记录的进度继续。[OpenAI ExecPlan 实践](https://developers.openai.com/cookbook/articles/codex_exec_plans)
- 完成验收后（采用五阶段流程时为阶段五），记录最终结果和遗留事项，再移至 [`Docs/exec-plans/completed/`](Docs/exec-plans/completed/)。

## 架构与代码

- 前端只通过 `/api/*` 访问后端，禁止直连数据库或执行系统命令。后端放在 `app/`，路由保持轻薄，业务进 `services/`，服务层不依赖 FastAPI 对象，外部系统经 `adapters/` 封装。宿主长任务走 `app/tasks/` 状态机，禁止在请求线程执行长任务。
- 前端放在 `web/src/`，组件用 `PascalCase.tsx`、hooks 用 `useXxx.ts`。启动器在 `launcher/`。后端文件、函数、字段及 API 出入参用 `snake_case`，类用 `PascalCase`，常量用 `UPPER_SNAKE`。
- 数据表用复数 `snake_case`，主键用 `id`，时间字段用 `created_at`、`updated_at`（ISO 8601 文本）。状态用短字符串，`tasks.status` 统一为 `pending/running/success/failed`，清理逐项状态查技术架构。
- 不引入微服务、消息队列或常驻守护进程，不擅自添加重依赖。未获用户明确批准，不将后续规划排入当前任务或提前实现。
- 计划管理固定为默认首页 `/` 和主导航第一项。其他导航与数据管理分组见产品需求。
- 微信检索、总结、向量逻辑只做接口适配，不重写。总结请求统一经 Agent 的 `summarize_chat` 工具触发（D2），禁止 Service 直调 `run_summary`。工具 docstring 属于提示词，修改须做行为回归。允许自动启动设置中配置的 WeChatDataAnalysis（D5）。
- Chroma 沿用 `chat_chunks`、`rag_state` 集合，metadata 键用 `snake_case`。文档 ID 沿用确定性哈希 `sha1(chat_id|msg_ids)`，禁止用随机 UUID 作幂等键。

## 模型、日志与异常

- 所有 LLM 请求均设置 `response_format={"type":"json_object"}` 或供应商等效的原生 JSON 约束。Agent 每轮请求都启用，工具轮保留原生协议，最终回答为 JSON 对象。提示词定义字段和类型，消费方解析并校验。Markdown 或自然语言放入明确的字符串字段（如 `content_md`），解包后展示或落库。
- 输出非法时显式失败或降级。供应商拒绝 JSON mode（如 HTTP 400 或 `invalid_request_error`）时，由模型封装统一转为领域错误，包含模型名与非敏感原因摘要，记录日志并通过任务状态或降级结果向调用方暴露。禁止关闭 JSON mode 重试、退为纯文本或静默切换模型。
- 使用模块级 `logging`，禁止裸 `print`。文件日志按天轮转至 `data/logs/`，仅记录时间、任务 ID、操作类型、数量、结果、耗时和非敏感错误摘要。禁止记录聊天正文、Agent 完整回答、密钥及私人内容。
- 外部调用设置超时，最多重试两次并指数退避。禁止无限重试和裸 `except:`。服务抛领域异常，API 统一映射为 `{detail:{code,message}}`。后台异常写入对应的任务状态记录。
- Windows 的 `.bat`、`.vbs`、`.cmd`、`.ini` 仅用 ASCII，中文说明写入配套 Markdown 或 Python docstring。

## 数据安全

- 开发、调试、迁移验证及破坏性测试使用隔离副本或临时库。测试代码禁止使用真实聊天库或真实 Chroma 目录作为写路径。对唯一真实聊天库做不可逆操作前，先说明风险并取得用户批准。禁止清空、重置或覆盖真实业务数据，禁止自行执行破坏性迁移。
- 禁止自动删除数据。删除须经清理审核流程人工勾选并确认。微信两库的删除只允许经 `app/cleanup/`，使用专用读写连接、复检保护日期并持久化状态。`2026-10-27` 为保护日期，可用 `PH_PROTECTED_DATES` 扩展。其余聊天 SQLite 访问使用 `mode=ro`。禁止读写 WeChatDataAnalysis 管理的原始微信数据库。
- `hub.db` 的 Schema 变更全部走 Alembic，先在隔离副本验证，应用到真实库前留备份。聊天快照和归一化库沿用现有 Schema，不改表结构、不走 Alembic。第一版产品不实现备份与恢复功能（D1）。
- 密钥统一经 `env_bootstrap.load_hub_env()` 加载。权威文件为仓库之外的 `~/.personal-hub/.env`，项目根 `.env` 可选覆盖，键名见 [.env.example](.env.example)。任何提交不得包含密钥。
- `Output/` 的历史报告与问答文件兼容保留，未经用户确认不得清理（D8）。随手备忘和重要信息不入 Git、不进文件日志正文、不参与清理审核。

## 验证与 Git

```bash
python -m pytest
cd web && npm test
cd web && npx tsc --noEmit
cd web && npm run build
```

- 默认 Mock LLM、Embedding 与外网请求，使用假模型、respx 和 fixture，做到零付费、零外网、零真实生产数据。真实模型验证单独标记 LIVE。模型测试须验证实际请求参数、输出解析及供应商不支持 JSON mode 的错误路径。
- 修 Bug 先写复现测试，禁止删除失败测试或放宽断言。服务层与状态机行覆盖率参考目标为 80%。
- 目录或模块迁移前后运行同组基线测试，确认 Agent 工具输出、报告 Schema 和检索结果一致（D3）。改变 `app/wechat_agent/` 行为前先写明工具、流水线和提示词的影响面，跑单轮问答与单日总结冒烟，迁移或多群改动还要对拍历史输出。
- 未获用户明确授权，不执行 `git commit`、`push` 或 `tag`。获准提交时用中文简述变更意图。

## main / V3 Worktree

两处工作区适用同一套规则。会话开始时执行 `git branch --show-current`，对照当前路径确认身份。无法确认时先问用户。

| 工作区与分支 | 职责 |
| --- | --- |
| `E:/wechat-LangGraph` · `main` | 维护现有模块，包括修复、优化、重构和稳定性验证。未经授权不开发 V3 专属功能。修改共享 API 或数据结构时评估并汇报对 V3 的影响。 |
| `E:/wechat-LangGraph-v3` · `codex/V3` | 执行用户明确批准的 V3 工作。优先用新增模块、扩展接口和独立组件，避免主动重构或优化现有模块。确需改动现有核心模块时，先说明影响并获授权。 |

- 两边可并行开发，各自只操作当前工作区及其运行环境。禁止擅自切换到对方分支、修改其他工作区、操作对方未提交内容或覆盖对方分支。优先用独立测试库、端口和缓存命名空间。不得重建已废弃的 V1 工作区或 `feature/V1` 分支。
- 未获明确授权，禁止 `git reset --hard`、`git clean -fd`、`git push --force`、删除 Worktree 或分支、跨工作区修改和跨分支同步或合并（含 `merge`、`cherry-pick`、`rebase`）。需要同步时说明范围和冲突点，由用户决定并默认执行。共享规范应保持两分支一致，由用户操作或明确授权后分别应用同一变更。
- 改动共享接口、数据库结构或配置前先检查兼容性。改动前排查并行冲突，发现同文件或逻辑被同时修改时缩小改动面并汇报，由用户裁决，不处理对方分支冲突。
- Alembic revision ID 由工具生成，禁止手写或复用对方 ID，核对依赖与 migration heads。两边涉及同一表时先报告并协调，合并时保留双方迁移文件，`down_revision` 冲突由用户裁决。
- 工作区规则发生冲突或歧义时先报告，保持架构约束优先，数据安全按更严格的要求执行。
- 完成时汇报工作区与分支、完成项与文件、验证命令和结果、共享接口或数据库影响、配合或同步需求、Git 状态及已提交时的 Commit Hash。说明未解决问题与验证失败。
