# 环境审计报告（验证前）

> 审计方式：只读检查仓库代码、依赖清单、迁移文件、数据库文件头、Docker 版本、前端配置。未修改任何文件。
> 审计日期：2026-11-08。

## 1. 后端

| 项 | 实际情况 | 证据 |
|---|---|---|
| 语言/解释器 | Python 3.13.18（Conda `agent` 环境，`D:/miniconda/envs/agent/python.exe`） | `python.exe --version` |
| Web 框架 | FastAPI 0.135.1 + uvicorn 0.46.0，入口 `app.main:create_app`，端口 8620 | requirements.txt、app/main.py、launcher/launch.py |
| 分层 | `app/api`（薄路由）→ `app/services` → `app/adapters`；长任务走 `app/tasks` 状态机 | 目录结构 |
| ORM/迁移 | SQLAlchemy 2.0.48 + Alembic 1.20.1，迁移到 `0010_github_integration.py` | alembic/versions/ |
| 主库 | `data/hub.db`（SQLite），另有 pre-0005~pre-0010 迁移备份 | data/ |
| 日志 | 模块级 logging，按天滚动到 `data/logs/` | AGENTS.md、app/logging_config.py |

## 2. 依赖可用性（agent 环境实测 `pip list`）

已装且与本验证相关：langgraph 1.1.2、langgraph-checkpoint 4.0.1、langchain 1.2.12、langchain-openai 1.1.11、langchain-deepseek 1.0.1、openai 2.26.0、dashscope 1.25.6、httpx 0.28.1、feedparser 6.0.14、tenacity 9.1.4、beautifulsoup4 4.14.3、lxml 6.1.0、respx 0.23.1、pytest 9.0.3、sse-starlette 3.3.4、chromadb 1.5.9（仅微信检索用）、scikit-learn 1.8.0、numpy 2.4.4、scipy 1.17.1。

**缺失**（需 `.venv-probe` 或 Docker）：qdrant-client / Qdrant Server、APScheduler、simhash / datasketch、rank-bm25、sentence-transformers、trafilatura。

## 3. 现有业务模块（与晨报相关的先例）

- 资讯中心：`app/adapters/news_rss.py`（feedparser，含超时/重试/UA）、`news_hn.py`、`news_common.py`（RawNewsItem 统一结构、`MAX_RETRIES=2` 指数退避、`MAX_ITEMS_PER_SOURCE=100`）；`app/services/news_service.py`、`news_scoring.py`、`news_translation.py`；模型 `app/models/news.py`。
- GitHub 集成：`app/models/github.py`（repos/commits/PRs/issues）、`app/adapters/github_source.py`、`app/services/github_service.py`、`github_contrib.py`。
- 个人数据：`app/models/plan.py`（long_term_plans / daily_tasks）、`task.py`、`reading.py`、`important_info.py`、`memo(s).py`、`token_usage.py`（模型调用费用记录先例）。
- 微信 Agent：`app/wechat_agent/agent.py` + chat_tools，使用 LangChain/LangGraph，LLM 配置 `llm_config.json`（默认 `qwen3-vl-plus`，base_url 为 DashScope 兼容模式）。

## 4. 密钥与环境变量

- 权威密钥文件 `~/.personal-hub/.env`（仓库外），项目根 `.env` 可选覆盖；统一经 `env_bootstrap.load_hub_env()` 加载；`PH_USER_ENV_DIR` 可重定向（测试用）。
- `.env.example` 声明：DASHSCOPE_API_KEY（必填）、DEEPSEEK_API_KEY（可选）、GITHUB_TOKEN（可选）、LANGSMITH_*（可选）。
- 本轮不读取、不打印任何密钥值；脚本仅检测 key 是否存在（布尔）。

## 5. 前端

- React + TypeScript + Tailwind（`web/`，Vite）；页面：`HomePage/NewsPage/PlansPage/ReadingPage/WechatPage/GithubPage/CleanupPage`。
- API 客户端在 `web/src/api/*.ts`；实时通信：后端已装 `sse-starlette`（微信模块流式回答先例待核查，见 T17）。

## 6. 本轮临时资源

| 资源 | 用途 | 清理方式 |
|---|---|---|
| `.venv-probe/` | pip 安装 qdrant-client、APScheduler、datasketch、rank-bm25 等探针依赖 | 可整体删除 |
| Docker 容器 `tv2-qdrant`（qdrant/qdrant 最新，端口 8633，临时 volume） | T12–T14、T21、T22、集成测试 | `docker rm -f tv2-qdrant` + `docker volume rm` |
| Collection `tv2_news` / `tv2_reports` | Qdrant 测试 | 随容器删除 |
| 隔离 SQLite（临时目录） | T1 对照、T7/T10/T14/T16 场景 | 删除文件即可 |

## 7. Docker / 系统

- Docker version 28.3.3 可用（`docker --version`）。
- 未发现既存 Qdrant 实例/容器；端口 8633 未被占用（T12 实测确认）。
- Windows 主机，时区按 Asia/Shanghai 处理（代码中以 `zoneinfo` 显式指定，不依赖系统时区）。
