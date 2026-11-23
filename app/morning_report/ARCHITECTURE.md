# 今日晨报架构

## 系统概览

今日晨报是个人助手的可选模块，页面入口为 `/morning`。它采集国内、国际和 AI 资讯，用个人助手数据库中的记录生成昨日回顾与行动建议，并发布可查看的报告版本。页面还提供历史报告、新闻收藏和生成进度。后端由 FastAPI 路由、进程内任务执行器、业务服务、外部适配器和 LangGraph 工作流组成，运行数据保存在晨报自己的 SQLite 中。

## 整体架构

- 宿主通过 `app/main.py` 的 `_init_morning_report` 初始化数据库、任务执行器和路由，按配置启动调度器。可选模块的就绪状态控制页面和 API 的访问时机。
- React 页面通过 `/api/morning/*` 查询报告、新闻与进度，或提交采集和生成任务。定时调度与手动入口都把长任务交给 `MorningRunner`，生成逻辑集中在 `run_generate`。
- 生成服务从新闻适配器和个人库准备输入。LangGraph 按顺序运行资料整理、个人决策分析、正文组装和发布。只有两个个人分析节点调用 DashScope，其余环节由程序处理。

## 代码地图

| 要查找的功能 | 阅读入口 |
| --- | --- |
| 页面、正文渲染与前端请求 | `web/src/pages/MorningReportPage.tsx`、`web/src/components/MorningReportBody.tsx`、`web/src/api/morning.ts` |
| API 与数据契约 | `api/__init__.py` 聚合路由，`api/runs.py` 处理采集、生成和停止，`api/report.py` 处理版本查询与重跑，`api/news.py` 处理星标和收藏。接口模型见 `schemas.py` 与对应路由。 |
| 调度、执行和进度 | `services/scheduler.py` 负责定时提交，`services/runner.py` 管理运行状态和取消，`services/progress.py` 记录阶段，`api/progress.py` 对外提供快照与事件流。 |
| 资讯接入与个人数据 | `services/news_pipeline.py` 调用 `adapters/chinanews.py` 和 `adapters/aihot.py`，保存采集结果。个人证据从 `services/hub_readonly.py` 进入。 |
| 分析、正文与发布 | `services/report_service.py` 准备输入并调用 `graph/workflow.py`。分析代理与工具分别见 `graph/subagents.py`、`services/decision_tools.py`。正文与结构化内容见 `services/report_assembly.py`、`services/report_news_content.py`，重新组装入口见 `services/report_actions.py`。 |
| 存储与配置 | `db.py` 管理晨报 SQLite 和迁移，`models.py` 定义运行、资讯、报告版本和收藏等持久化模型，`config.py` 定义模块设置。 |

## 核心流程与数据流

1. **触发与采集。** 启用调度时，APScheduler 默认每天北京时间 08:30 提交当期生成，已有待执行、运行中或已产出结果的当期生成任务时跳过。手动 API 支持单独采集、生成与重新生成。生成会复用符合当前采集策略且覆盖完整的当期采集结果，缺失或不符合时补采。中新网取国内、国际官方热点榜并合并同事件，文章发布时间用于展示。AI 资讯按 AIHOT 日报归属日期收录。采集批次、新闻与覆盖缺口写入晨报库。
2. **准备个人证据并分析。** 生成服务从配置指定的个人库读取任务、长期计划、重要信息、备忘和阅读记录，个人回顾的时间窗口为北京时间 `[前一天 08:00, 当天 08:00)`，部分证据以快照随任务保存。图中先整理资讯和个人上下文，再串行运行 `GoalAnalysis` 与 `ActionSuggest`。两个分析代理只获得本轮个人上下文及其只读检索工具，建议节点还接收目标分析结果。
3. **组装、发布和读取。** 主编节点将当期资讯和分析结果组装成 Markdown，发布节点同时保存结构化内容及组装输入。资讯缺失会显示原因，个人分析或数据读取失败可产生降级结果。首个发布版本标为主报告，历史列表按天显示最新发布版本，旧版本仍可查询。新闻星标与收藏备注、重点状态由晨报库独立持久化。
4. **重新组装。** `/reassemble` 从指定已发布版本恢复组装输入，直接执行主编和发布节点。它创建新版本，沿用原有资讯和分析结果。缺少必要输入时返回显式错误。

## 架构边界与约束

- **数据归属。** 晨报写入宿主数据目录下的 `morning_report.db`，由模块自己的迁移器管理。生成路径用 SQLite `mode=ro` 和 `query_only` 打开配置的个人库，读取失败会记录缺口，不回退到其他数据库。独立的 `/personal_context` 查询通过宿主注入的会话执行只读查询，与生成路径使用不同的读取入口。
- **分析与正文。** 决策工具只检索本轮个人记录，无新闻、历史晨报或历史建议检索入口。两个代理的请求均使用原生 JSON mode 和原生工具协议，消费端解析并校验结果。模型拒绝 JSON mode 时转换为领域错误，由节点显式降级。正文采用程序组装，DeepSeek 备用客户端未接入当前流程。
- **保留实现。** Qdrant、Embedding 和通用 RAG 实现仍在 `services/{qdrant_store,index_sync,rag_tool}.py` 与 `adapters/embedding.py`，当前生成和发布链路没有接线。旧新闻适配器也仍在代码树中，实际采集来源以 `run_collect` 为准。旧晨报助手与 Memory API 已停用，`Memory` 模型保留用于兼容历史 Schema。

## 横切关注点与文档导航

- **配置。** 晨报继承宿主加载的环境变量，模块设置使用 `PH_MR_` 前缀。个人库路径和 DashScope 模型分别由 `PH_MR_PERSONAL_DB_PATH` 与 `PH_MR_DASHSCOPE_MODEL` 控制。实际部署的覆盖值待确认。
- **任务与诊断。** 执行器通过进程内线程池运行任务，阻止同类任务并发提交，停止请求由执行路径在检查点协作处理。宿主启动时将遗留的待执行和运行中任务标为失败。阶段进度、运行日志和用量保存在晨报库，页面通过快照和 SSE（服务器发送事件）获取进度。LangGraph 检查点使用单独的 SQLite 文件。采集 HTTP 和模型调用各自配置超时及有限重试。
- **文档与验证入口。** 宿主装配见[项目架构](../../ARCHITECTURE.md)，业务规则见[产品需求 §7](../../Docs/PRD.md#7-今日晨报v2-已完成能力)，详细设计及历史演进见[技术架构](../../Docs/Architecture.md)，开发约束见[晨报开发规范](AGENTS.md)。回归场景见 `tests/test_morning_*.py` 与 `web/src/test/morning*.test.tsx`。
