# AGENTS.md — 个人助手开发规范

约束本仓库的所有开发者与 AI 编码助手。需求与业务规则见 `Docs/PRD.md`，技术架构见 `Docs/Architecture.md`，各阶段功能规划见 `Docs/DEVELOPMENT_PLAN.md`。`wechat-chat-summary/` 是独立上游项目（已被 .gitignore 忽略），不适用本规范。

## 1. 项目定位与运行环境

- 个人使用的 Windows PC 应用：FastAPI + React，浏览器访问（默认 127.0.0.1:8620），**仅面向 PC，不做移动端适配**（V2.0 需求）。
- 核心定位：**个人数据驱动的智能工作助手**——整合计划、备忘、重要信息、阅读记录及未来接入的 GitHub 等个人数据，利用 AI 进行信息整理、关联分析、总结和建议（目标与原则见 `Docs/DEVELOPMENT_PLAN.md`）。
- 运行环境：Conda 环境 `agent`（Python 3.13）；前端 `cd web && npm install && npm run build`。
- 当前版本含：微信聊天助手（Agent 对话/总结/同步）、技术资讯 TOP 10、计划管理、阅读管理、三栏工作台（右侧栏=重要信息 SQLite + 随手备忘 SQLite 多条记录，可与每日任务双向转换；旧 `~/.personal-hub/memo.md` 已废弃，启动时幂等迁移、原文件保留不入 Git）。
- 微信模块已迁入 `app/wechat_agent/`；`GetWechatInfo/` 仅保留聊天数据（DataInfo/ 两库 + VectorStore/）。原 `LangGraph/`、`Tool/` 目录已不存在。
- 常驻决策（不必再问）：总结统一经 Agent（D2，见 §4）；第一版无备份功能，以数据隔离规范替代（D1）；允许自动启动设置中配置的 WeChatDataAnalysis（D5）。

## 2. 代码组织与命名

- 后端分层：`api/`（路由薄层）→ `services/`（业务，不得 import FastAPI 对象）→ `adapters/`（外部系统封装）；长任务走 `tasks/` 状态机。
- 新代码目录归属：后端进 `app/` 对应分层；前端 `web/src/`（组件 PascalCase.tsx，hooks/useXxx.ts）；启动器 `launcher/`。
- 命名：文件/函数/字段 snake_case；类 PascalCase；常量 UPPER_SNAKE；API 出入参统一 snake_case。
- 数据库：表 snake_case 复数、主键 `id`、时间 `created_at/updated_at`（ISO8601 文本）；状态用短字符串枚举。**hub.db 全部 Schema 变更走 Alembic**；聊天两库（快照/归一化）沿用现有 Schema，不走 Alembic、不改表结构。
- Chroma：Collection 名与现有 `chat_chunks`/`rag_state` 保持一致；文档 ID 用确定性哈希（现有规则 sha1(chat_id|msg_ids)），**禁止随机 UUID 作幂等键**；metadata 键 snake_case。
- 状态枚举：`tasks.status` 统一 pending/running/success/failed；清理逐项中态见 Architecture 清理模块设计。

## 3. 架构铁律

1. 前后端彻底分离：前端只调 `/api/*`，禁止直连数据库、执行系统命令。
2. 业务逻辑写在 `services/`；外部系统（WeChatDataAnalysis、HN、RSS 等）一律经 `adapters/` 封装。
3. 长任务（总结、同步、刷新、清理执行）必须走 `tasks/` 状态机，禁止在请求线程跑长任务。
4. 不引入微服务/消息队列/常驻守护进程；不新增未经讨论的重依赖。
5. 微信检索/总结/向量逻辑零重写，只做接口适配（Agent 工具 docstring = 提示词，**改 docstring = 改模型行为**，改动须先跑回归冒烟）。
6. **总结统一经 Agent（D2）**：所有总结请求必须经 Agent 的 `summarize_chat` 工具触发；禁止 Service 直调 `run_summary` 的旁路。
7. **禁止自动删除**：任何数据删除必须经清理审核流程人工勾选 + 确认；系统不得存在自动删除入口（清理审核见 Architecture §3.4）。
8. **未来需求不进当前计划**：未经用户明确批准，不得把 `Docs/DEVELOPMENT_PLAN.md` "未批准的后续规划"中的需求排入当前开发或提前实现。

## 4. 数据与安全（最高优先级）

- **数据隔离铁律（D1 配套）**：开发、调试、迁移验证、破坏性测试一律使用隔离副本或临时库；测试代码禁止出现真实聊天库/Chroma 真实目录的写路径（conftest 有数据隔离守卫）。对唯一真实聊天库执行任何**不可逆操作前，必须先向用户说明风险并获得批准**。
- 第一版不实现备份/恢复（D1，V2.0 需求）；不得擅自加回。
- hub.db 迁移脚本必须在隔离副本验证通过后才应用于真实库；应用前留备份。
- 密钥权威文件在 `~/.personal-hub/.env`（仓库之外）；项目根 `.env` 仅可选覆盖；键名见 `.env.example`；统一经 `env_bootstrap.load_hub_env()` 加载；**任何提交不得包含密钥**。
- 聊天相关 SQLite 一律 `mode=ro` 打开；禁止读写 WeChatDataAnalysis 管理的原始微信数据库。
- `Output/` 历史报告与问答文件兼容保留，未经用户确认不得清理（D8）。
- 随手备忘（memos 表）与重要信息属用户私人内容：不入 Git、不进文件日志正文、不参与清理审核。
- 清理审核硬约束：微信两库的删除只能走 `app/cleanup/` 通道（独立读写连接、保护日期复检、状态机落库）；`2026-10-27` 为保护日期（`PH_PROTECTED_DATES` 可扩展），任何删除入口不得绕过。

## 5. 日志与异常

- 新代码用模块级 `logging`，禁止裸 `print`；按天滚动到 `data/logs/`。
- **文件日志隐私白名单**：只记时间、任务 ID、操作类型、数量、结果、耗时、非敏感错误摘要；**禁止**记录聊天正文、Agent 完整回答、密钥。
- 外部调用必须设超时；重试最多 2 次、指数退避；禁止无限重试与裸 `except:`。
- 服务层抛领域异常，API 层统一映射 `{detail:{code,message}}`；后台任务异常必须落任务表，禁止静默吞掉。
- **Windows 脚本与 ini 必须纯 ASCII**（.bat/.vbs/.cmd/.ini 不得含非 ASCII 字符，中文说明写在配套 .md 或 Python docstring）。

## 6. 测试与验证

```bash
python -m pytest                     # 后端（隔离临时库）
cd web && npm test                   # 前端 Vitest
cd web && npx tsc --noEmit           # 类型检查
cd web && npm run build              # 正式构建
```

- LLM/Embedding/外网一律 Mock（fake LLM、respx、fixture），默认零付费、零外网、零真实生产数据。
- 修 bug 先写复现测试；禁止删失败测试、禁止给断言放水。
- 目录/模块迁移必须回归对拍：迁移前后同一组基线测试（Agent 工具输出、报告 Schema、检索结果）均绿且一致（D3）。
- 改动 `app/wechat_agent/` 任何行为前：写明影响面（工具/流水线/提示词）→ 跑单轮问答 + 单日总结冒烟 → 迁移/多群相关改动对拍历史输出。
- 覆盖率参考目标：服务层与状态机行覆盖 ≥ 80%。

## 7. Git 与提交

- **未经用户明确要求，不得执行 git commit / push / tag**；完成开发后只汇报，等用户指示。
- 用户要求提交时：commit message 用中文简述变更意图。

## 8. Git Worktree 多 Agent 并行开发规范（V1/V2 共同规则）

本项目使用 Git Worktree 双工作区并行开发，两个工作区各运行一个独立 Coding Agent，本节规则对两个工作区**完全同等适用、不可互相豁免**。各 Agent 在任何文件操作前先读本文件并执行身份确认。

- **工作区身份识别**：会话开始先用 `git branch --show-current` 确认所在分支，按下表识别身份；身份无法确认时先询问用户，不得猜测行事。

  | 检出分支 | 工作区 | 身份 | 职责 |
  |---|---|---|---|
  | `feature/V1` | `E:/wechat-LangGraph-v1` | V1 | 维护与优化现有模块（微信聊天助手、技术资讯、计划管理、阅读管理、三栏工作台、清理审核等） |
  | `feature/V2` | `E:/wechat-LangGraph-v2` | V2 | 开发 V2 新模块（范围以用户当次明确批准的需求为准，见 §3 铁律 8） |
  | `main` | `E:/wechat-LangGraph` | 主工作区 | 集成与发布，原则上不由 Agent 直接开发 |

- **职责边界**：只允许修改本工作区当前任务范围内的代码与文档；越界修改（其他模块、共享文件如 `AGENTS.md`/`Docs/`、构建配置）必须先向用户说明影响并获得**明确授权**后方可进行。
- **禁止互相修改工作目录**：不得进入另一工作区目录读写文件、执行 `git checkout/reset/rebase/merge` 等写操作，或以符号链接/绝对路径方式改动对方文件；一切跨工作区改动只能由用户亲自执行或明确授权后执行。
- **不得修改其他功能代码或数据库**：不改动与本任务无关的模块代码；不对其他工作区指向或共享的数据库文件（hub.db、聊天两库、Chroma 目录）执行任何写操作；数据库相关约束继续遵守 §4。
- **Git 安全（高风险操作一律需用户授权）**：未经用户明确授权，禁止跨分支合并（`merge`/`cherry-pick`/`rebase` 到本工作区检出分支之外的分支）、`git reset --hard`、强推（`--force`）、`git clean`、`git worktree remove/prune`、`git branch -D`。普通开发流程仍遵守 §7（不擅自 commit/push）。
- **代码同步**：需要吸收对方工作区改动时，Agent 只提出同步建议（涉及文件、潜在冲突点），由用户决定合并时机与方式；合并动作默认由用户在主工作区或指定工作区执行。共享文件（如本规范）的修订需保持两分支一致：由用户操作，或经用户授权后在 `feature/V1` 与 `feature/V2` 两个分支上分别应用**同一内容**的改动。
- **数据库迁移（Alembic）**：各工作区新增的 `alembic/versions/` 迁移由 Alembic 自动生成 revision id，禁止手写或复用对方 id；迁移脚本先在隔离副本验证（§4），两工作区对同一表结构的迁移需先汇报用户协调顺序，合并时保留双方版本文件，`down_revision` 链冲突由用户裁决。
- **冲突预防与处理**：改动前先考虑对方是否可能在改同一文件；发现并行修改同一文件或同一段逻辑时，在本工作区内完成并最小化改动面，汇报中显式标注冲突点，交由用户裁决，不自行解决对方分支的冲突。
- **任务汇报**：每次任务结束时汇报：所在工作区与分支、修改文件清单、验证结果（§6 命令及产物）、是否触碰越界文件、是否需要另一工作区关注。汇报中说明影响面与遗留风险，不隐瞒失败。
- **规则冲突处理**：本节规则与既有规则冲突，或本节内部存在歧义时，先向用户报告冲突点，不擅自覆盖或修改既有规则（§3 铁律优先级不变）。

## 9. 文档维护规则

各文档职责（单一信息源，避免内容重复）：

- `README.md`：项目介绍、启动方式和使用入口。
- `AGENTS.md`：AI 开发规范及本文档维护原则。
- `Docs/PRD.md`：产品需求与业务规则的唯一权威来源。
- `Docs/Architecture.md`：技术架构与设计的唯一权威来源。
- `Docs/DEVELOPMENT_PLAN.md`：各阶段功能规划，不承担进度追踪职责。
- `Docs/ADR/`：仅按需记录重大技术决策及其取舍。

维护原则：

- 普通代码修改不需要更新文档；需求、架构或功能规划发生实质变化时更新对应文档，并先核对实际代码。
- 不单独维护 `TEST_PLAN.md`、`ROADMAP.md`、`CHANGELOG.md`（测试场景由 `tests/` 维护，后续规划并入 DEVELOPMENT_PLAN，开发历史由 Git 记录）。
- 不为普通 UI 调整、小型重构创建 ADR。涉及重大技术决策（多模块影响、明显方案权衡、修改成本高、未来难从代码理解原因）时，先向用户说明理由与备选方案，再建议是否写入 `Docs/ADR/`。
