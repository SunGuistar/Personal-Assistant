# AGENTS.md — 今日晨报开发规范

## 范围与导航

今日晨报负责采集资讯、分析个人记录、发布报告版本。宿主提供页面路由、模块装配及数据目录，晨报维护自己的运行和存储。后端在 `app/morning_report/`，宿主装配在 `app/main.py`。前端从 `web/src/pages/MorningReportPage.tsx` 和 `web/src/api/morning.ts` 进入，测试在 `tests/test_morning_*.py` 与 `web/src/test/morning*.test.tsx`。本规范也适用于这些目录中的晨报改动。

- 通用规范见[根目录 AGENTS.md](../../AGENTS.md)。查找当前流程、依赖和代码入口时读[模块架构](ARCHITECTURE.md)。
- 本轮目标与成功条件见[项目目标](GOALS.md)，固定任务范围和阶段产出见[晨报专项计划](PLANS.md)。规划项须经相应阶段确认后实施。
- 当前业务规则以[产品需求](../../Docs/PRD.md)的晨报章节为准，详细设计见[技术架构](../../Docs/Architecture.md)。V2 原始需求可作历史参考。[开发规划](../../Docs/DEVELOPMENT_PLAN.md)中的既有晨报阶段记录沿用当时的编号。
- 阶段二确认目标时产出 GOALS 和 Product Specs，阶段三产出 Design Docs。当前[产品规格索引](docs/product-specs/index.md)与[设计文档索引](docs/design-docs/index.md)均为空，尚无可引用的 V3 对应文档。

## 本轮五阶段开发

1. 按「项目分析 → 目标与规格 → 架构与计划 → 实施 → 验收」推进。开始任务前确认当前阶段和授权范围，按需阅读当前阶段的文档。未获授权不得进入后续阶段。各阶段职责与产出见[晨报专项计划](PLANS.md)。
2. 需要 ExecPlan 时通常在阶段三建立，进行中放在[执行计划目录](docs/exec-plans/active/)，阶段五验收后归档至[已完成目录](docs/exec-plans/completed/)。编写与维护遵循[根规范](../../AGENTS.md#文档维护与执行计划)。
3. 实施以已确认的规格和设计为依据。验收按约定的成功条件提交实际测试或评估证据，列出未验证项目。发现前序规格或设计有问题时，明确反馈差异，并在授权范围内修订相关文档和验收依据。
4. 五阶段是项目自主采用的流程。工程实践参考 OpenAI 公开资料，记录采纳依据与适用性，明确哪些是官方建议、公开案例或项目适配。[Harness Engineering](https://openai.com/index/harness-engineering/) · [Codex 工作流案例](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex)

## 当前实现的专属约束

- 采集和生成等长任务走 `MorningRunner` 及晨报运行记录。默认每天北京时间 08:30 触发，个人回顾窗口为 `[前一天 08:00, 当天 08:00)`。调度值见 `config.py`，窗口由 `hub_readonly.window_for` 定义。
- 晨报默认写入 `data/morning_report.db`，Schema 由 `db.py` 的迁移器和 `schema_migrations` 管理。开发、验证和迁移使用隔离数据库，晨报运行数据不入 Git。生成路径经 `PH_MR_PERSONAL_DB_PATH` 指定个人库，以 SQLite `mode=ro` 和 `query_only` 打开。禁止写入现有 `hub.db`、微信两库及 Chroma。
- 当前自动与手动生成由 LangGraph 编排，LangChain `create_agent` 运行目标分析、行动建议两个 Subagent。工具只使用本轮个人上下文。正文由程序组装，重新组装使用指定的历史版本输入。修改现行行为须依据确认后的规格与设计。
- 两个 Subagent 使用 DashScope 的 OpenAI 兼容端点，模型由 `PH_MR_DASHSCOPE_MODEL` 配置。按节点显式设置 Thinking，当前两者均关闭。遵守根规范的原生 JSON mode 规则，供应商不支持时走 `JsonModeUnsupportedError` 和显式降级。DeepSeek `deepseek-flash` 是备用，启用须获用户明确授权并通过允许时段检查，禁止静默切换。
- 保留的 Qdrant/RAG 实现未接入当前生成链路。使用 Qdrant 时固定走 `http://127.0.0.1:6333`，禁止使用 `localhost`。晨报专用集合为 `morning_tech_news`、`morning_reports`，测试不得写入这两个集合。[Qdrant ADR](../../Docs/ADR/0001-Qdrant客户端禁用localhost.md)

## 测试与汇报

在仓库根目录运行。后端使用已装项目依赖的 `agent` 环境，前端先按 README 安装依赖。

```powershell
python -m pytest -k "test_morning and not test_morning_stage3_rag"
npm --prefix web test -- morning
```

- 默认用假模型、假 Embedding、respx 和隔离数据 fixture。真实采集或模型验证标为 LIVE，与单测分开执行。需要验证保留的 RAG 实现时，可在隔离的本地 Qdrant 环境运行 `python -m pytest tests/test_morning_stage3_rag.py`。用 `tmp_mr_*` 集合及假 Embedding，测试后清理临时集合。
- 完成时按根规范汇报，注明阶段、改动范围、实际执行的验证、未验证项与未解决问题。
