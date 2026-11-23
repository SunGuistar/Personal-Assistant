# 系统架构

## 整体概览

个人助手是面向单用户的 Windows PC 应用。它管理计划、备忘、阅读和知识记录，接入微信聊天与 GitHub 活动，并生成今日晨报。应用以计划管理为默认入口 `/`。

```text
Windows 启动器 → Uvicorn / FastAPI → 提供 React 构建产物
PC 浏览器 → React 页面 → /api/* → 领域服务 → SQLite、文件及外部系统
                                  └→ 进程内任务执行器 → 同步、总结、清理与晨报生成
```

`launcher/launch.py` 启动 `app.main:create_app`，默认监听 `127.0.0.1:8620`。`app/main.py` 装配路由、数据库会话与任务执行器，并在构建产物存在时托管 `web/dist/`。首页 API 先就绪，微信与清理、阅读、GitHub 和晨报随后按模块初始化。`app/module_startup.py` 保存就绪状态，前后端分别用它约束 API 请求与页面入口。

## 代码地图

| 领域 | 入口和职责 | 主要依赖与数据归属 |
| --- | --- | --- |
| 个人管理与知识 | `PlansPage`、`ReadingPage`、`KnowledgePage`、`ExperiencesPage` 经 `app/api/` 调用 `app/services/`。服务管理计划、重要信息、备忘、阅读笔记、每日一问与经验记录。 | `app/db.py` 与 `app/models/` 提供 Hub 的 SQLAlchemy 持久化。业务记录存入 `hub.db`，阅读附件存入文件目录。 |
| 微信聊天 | `app/api/wechat.py` 提供同步和 SSE 对话。`app/services/wechat_service.py` 协调同步，`app/wechat_agent/` 持有 LangGraph 对话、聊天检索和总结逻辑。 | `app/adapters/wechat_source.py` 封装上游接入。同步链路处理快照、归一化和 Chroma 索引。Agent 读取应用侧聊天数据，Hub 保存对话记录、任务与同步状态。 |
| 清理审核与存储 | `app/api/cleanup.py` 将审核和执行交给 `app/cleanup/`。`app/api/storage.py` 经库存服务和适配器提供存储概览。 | 清理用专用 SQLite 与 Chroma 访问层，审核状态存于 Hub。存储概览独立于清理执行。前端 `DataManagementPage` 汇集微信、清理、GitHub 与存储入口。 |
| GitHub | `app/api/github.py` 与 `app/services/github_service.py` 提供数据同步及活动查询。 | `app/adapters/github_source.py` 封装 GitHub API。同步后的仓库、活动与游标存入 Hub。 |
| [今日晨报](app/morning_report/ARCHITECTURE.md) | `app/morning_report/` 自带 `api/`、`services/`、`adapters/` 和 LangGraph `graph/`，负责新闻采集、筛选、个人分析、报告组装与运行进度。 | 独立 SQLite 和专用 Qdrant collections。通过只读适配读取个人数据，新闻和模型调用留在晨报域。 |

追查一条请求时，从 `web/src/App.tsx` 找页面，再看 `web/src/api/` 和对应后端路由。追查后台执行时，从提交点进入 `app/tasks/` 的 `TaskRunner`，或晨报域的 `services/runner.py` 与 `services/scheduler.py`。

## 架构不变量

- 浏览器通过 `/api/*` 访问业务能力。路由负责传输、校验和依赖装配，服务承载业务逻辑，适配器封装外部系统。
- 同步、总结、清理执行和晨报生成由进程内后台执行器管理。Hub 的任务状态落入 `tasks` 表，晨报维护自己的运行与阶段记录。
- 微信总结从 Agent 的 `summarize_chat` 工具进入，经 `app/services/wechat_jobs.py` 提交报告生成。聊天查询与索引构建使用只读聊天库连接。清理必须有人工选择和确认，并在执行时复检保护日期。
- LLM 请求按仓库约定启用供应商原生 JSON 模式，工具调用保留原生协议。消费方校验 JSON，模型不支持 JSON 模式或输出不合法时走显式错误路径。

## 依赖与数据边界

- **Hub** 持有通用业务表和任务状态。`alembic/versions/` 管理 `hub.db` 的 Schema。业务服务通过注入的数据库会话使用 Hub。
- **微信数据面** 由 `GetWechatInfo/DataInfo/` 的快照与归一化 SQLite，以及 `GetWechatInfo/VectorStore/` 的 Chroma 构成。应用与 WeChatDataAnalysis 通过适配器和快照衔接，原始微信数据库归上游管理。同步负责写入派生数据，删除权限集中在清理审核域。聊天库沿用自己的 Schema。
- **晨报数据面** 由晨报自身的迁移器维护 `morning_report.db`，向量索引使用本地 Qdrant。`services/hub_readonly.py` 提供跨域只读入口，个人数据路径可由晨报配置指定。自动与手动生成共用晨报工作流及运行记录。

## 横切关注点

- **配置与密钥**通过 `env_bootstrap.py` 加载。主应用设置在 `app/config.py`（`PH_`），晨报设置在自己的 `config.py`（`PH_MR_`）。密钥保存在用户目录的 `~/.personal-hub/.env`，项目本地 `.env` 可覆盖。
- **错误与诊断**由 `app/exceptions.py` 将领域错误和请求校验错误映射为 `detail.code` 与 `detail.message`。后台失败记录在对应执行器的持久化状态中。主应用通过 `app/logging_config.py` 写轮转日志，文件日志只记录非敏感诊断元数据。
- **访问边界**是仓库内启动器的本机回环监听。应用装配中未发现应用级登录或授权中间件。实际安装的监听覆盖、代理配置、数据路径和外部服务可用性属于运行环境，本次静态核对无法确认。
- **验证入口**为 `tests/` 与 `web/src/test/`。后端测试夹具以临时库隔离真实数据，外部服务与模型行为可通过替身验证。

详细设计见 `Docs/Architecture.md`，业务规则见 `Docs/PRD.md`，开发约束见 `AGENTS.md`。
