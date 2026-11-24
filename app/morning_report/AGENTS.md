# AGENTS.md — 今日晨报开发规范

## 范围与导航

今日晨报负责采集资讯、分析个人记录、发布报告版本。宿主提供页面路由、模块装配及数据目录，晨报维护自己的运行和存储。后端在 `app/morning_report/`，宿主装配在 `app/main.py`。前端从 `web/src/pages/MorningReportPage.tsx` 和 `web/src/api/morning.ts` 进入，测试在 `tests/test_morning_*.py` 与 `web/src/test/morning*.test.tsx`。本规范也适用于这些目录中的晨报改动。

- 通用规范见[根目录 AGENTS.md](../../AGENTS.md)。查找当前流程、依赖和代码入口时读[模块架构](ARCHITECTURE.md)。
- 本轮目标与成功条件见[项目目标](GOALS.md)，固定任务范围和阶段产出见[晨报专项计划](PLANS.md)。规划项须经相应阶段确认后实施。
- 当前业务规则以[产品需求](../../Docs/PRD.md)的晨报章节为准，详细设计见[技术架构](../../Docs/Architecture.md)。V2 原始需求可作历史参考。[开发规划](../../Docs/DEVELOPMENT_PLAN.md)中的既有晨报阶段记录沿用当时的编号。
- 阶段二确认目标时产出 GOALS 和 Product Specs。现有初稿和逐项确认的规则见[产品规格索引](docs/product-specs/index.md)，领域术语见[晨报术语表](GLOSSARY.md)。阶段三产出 Design Docs，见[设计文档索引](docs/design-docs/index.md)。

## 本轮五阶段开发

1. 按「项目分析 → 目标与规格 → 架构与计划 → 实施 → 验收」推进。开始任务前确认当前阶段和授权范围，按需阅读当前阶段的文档。未获授权不得进入后续阶段。各阶段职责与产出见[晨报专项计划](PLANS.md)。
2. 需要 ExecPlan 时通常在阶段三建立，进行中放在[执行计划目录](docs/exec-plans/active/)，阶段五验收后归档至[已完成目录](docs/exec-plans/completed/)。编写与维护遵循[根规范](../../AGENTS.md#文档维护与执行计划)。
3. 实施以已确认的规格和设计为依据。验收按约定的成功条件提交实际测试或评估证据，列出未验证项目。发现前序规格或设计有问题时，明确反馈差异，并在授权范围内修订相关文档和验收依据。
4. 五阶段是项目自主采用的流程。工程实践参考 OpenAI 公开资料，记录采纳依据与适用性，明确哪些是官方建议、公开案例或项目适配。[Harness Engineering](https://openai.com/index/harness-engineering/) · [Codex 工作流案例](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex)

## 当前实现的专属约束

- 采集和生成等长任务走 `MorningRunner` 及晨报运行记录。默认每天北京时间 08:30 触发，个人回顾窗口为 `[前一天 08:00, 当天 08:00)`。调度值见 `config.py`，窗口由 `hub_readonly.window_for` 定义。
- 晨报默认写入 `data/morning_report.db`，Schema 由 `db.py` 的迁移器和 `schema_migrations` 管理。开发、验证和迁移使用隔离数据库，晨报运行数据不入 Git。生成路径经 `PH_MR_PERSONAL_DB_PATH` 指定个人库，以 SQLite `mode=ro` 和 `query_only` 打开。禁止写入现有 `hub.db`、微信两库及 Chroma。
- 当前自动与手动生成由 LangGraph 编排，LangChain `create_agent` 运行目标分析、行动建议两个 Subagent。工具只使用本轮个人上下文。正文由程序组装，重新组装使用指定的历史版本输入。修改现行行为须依据确认后的规格与设计。
- 两个 Subagent 使用 DashScope 的 OpenAI 兼容端点，模型通过 `PH_MR_DASHSCOPE_MODEL` 显式配置，可按各模型免费额度调整。所选模型须支持原生 JSON mode、原生工具调用和当前的 Thinking 配置（两节点均显式关闭）。供应商不支持 JSON mode 时走 `JsonModeUnsupportedError` 和显式降级。禁止未经授权静默换模型或降级。启用备用 DeepSeek 模型须获用户明确授权并通过允许时段检查。
- 保留的 Qdrant/RAG 实现未接入当前生成链路。使用 Qdrant 时固定走 `http://127.0.0.1:6333`，禁止使用 `localhost`。晨报专用集合为 `morning_tech_news`、`morning_reports`，测试不得写入这两个集合。[Qdrant ADR](../../Docs/ADR/0001-Qdrant客户端禁用localhost.md)

## 缓存友好的上下文组装（Cache-aware Context Assembly）

本节适用于晨报应用中 Agent 的模型请求与上下文组装，Codex 内部上下文管理不在本节范围内。以下为提高 Prompt Cache 前缀复用率的工程优化原则，按任务和模型能力取舍。优先级为 **安全与权限约束 ＞ 数据正确性 ＞ 任务质量 ＞ 上下文有效性 ＞ 缓存性能**。可靠性及既有调用契约优先于缓存收益。

1. **静态前置。** 将稳定的 System / Developer 指令、任务规则、Few-shot 示例、工具定义与参数 Schema，以及任务内不变的参考资料尽量放在动态内容之前。保留 API 消息角色和指令优先级。
2. **动态后置。** 将当前时间与日期、用户输入、最新个人任务和计划、实时资讯与检索结果、工具结果和运行状态放在稳定内容之后。公共前缀避免混入时间戳、随机 ID 等易变字段。
3. **增量追加。** 多轮交互优先追加消息、工具调用及结果，避免反复重建、改写或重排已有历史。需要时纠正错误、移除无效或过期资料、压缩历史。按数据安全与权限规则移除不应保留的数据。
4. **确定性组装。** 相同逻辑输入尽量生成一致的表示。保持工具、Schema 和字段顺序以及序列化方式稳定，避免无意义的格式变动、无序集合迭代和随机或时间相关字段影响稳定前缀。
5. **按变化频率分层。** 区分长期稳定的核心规则、工具和示例，任务内稳定的背景和已确认资料，以及实时数据、工具结果和任务状态等动态上下文。优先稳定前两层，动态层尽量后置，内容按其语义归入适当的消息或请求字段。
6. **工具定义稳定。** 保持工具名称、描述、参数 Schema、顺序、加载和序列化方式稳定。沿用 Skills 与工具定义的按需披露，按 Agent 任务和授权范围选择工具，兼顾正确性、上下文成本与前缀稳定性。
7. **受控压缩。** 内容过长、过期或影响模型效果时，按需裁剪、摘要或压缩。保留必要指令、关键业务状态和已确认决策。摘要中的事实沿用原有证据与校验要求。
8. **缓存可观测性。** 在供应商支持时，以实际请求的输入 Token、缓存命中 Token、缓存写入 Token、延迟和 Token 成本评估收益。指标遵守既有日志和数据安全约束。

按当前配置的供应商和模型查阅其文档，确认缓存门槛、有效期、命中方式及 API 支持。模型切换时分别核验，避免依赖跨模型缓存共享或统一缓存策略。继续遵守本规范的 JSON mode、原生工具调用能力检查及禁止静默换模或降级的约束。具体组装结构、缓存机制和验证方案留待阶段三设计。

## 测试与汇报

在仓库根目录运行。后端使用已装项目依赖的 `agent` 环境，前端先按 README 安装依赖。

```powershell
python -m pytest -k "test_morning and not test_morning_stage3_rag"
npm --prefix web test -- morning
```

- 默认用假模型、假 Embedding、respx 和隔离数据 fixture。真实采集或模型验证标为 LIVE，与单测分开执行。需要验证保留的 RAG 实现时，可在隔离的本地 Qdrant 环境运行 `python -m pytest tests/test_morning_stage3_rag.py`。用 `tmp_mr_*` 集合及假 Embedding，测试后清理临时集合。
- 完成时按根规范汇报，注明阶段、改动范围、实际执行的验证、未验证项与未解决问题。
