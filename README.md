# 个人助手（Personal Hub）

运行在 Windows 本地的个人信息与事务管理平台：FastAPI 后端 + React 前端，浏览器访问，本地优先、单用户。**当前版本仅面向 PC 浏览器**。

**核心定位：个人数据驱动的智能工作助手**——整合计划、备忘、重要信息、阅读记录及未来接入的 GitHub 等个人数据，利用 AI 进行信息整理、关联分析、总结和建议（规划见 `Docs/DEVELOPMENT_PLAN.md`）。

当前开发方向（仅规划，均未实现）：GitHub 数据集成（REST API）→ 每日工作简报 → 长期记忆 → Agent 工程能力增强。

## 主要功能

- **首页工作台**：今日计划、正在读的书、近期热门资讯、系统状态一览
- **计划管理**：长期计划（重要置顶、标记完成、历史、具体目标）与每日任务（今日/逾期统一排序、历史只读）；两模块完全独立
- **阅读管理**：书籍与阅读状态、重要标记、云记导出笔记（PDF/PNG）上传与在线预览
- **技术资讯**：近期热门 TOP 10（多来源抓取、规则评分、中文标题摘要自动翻译缓存）+ 外部资讯导航
- **微信聊天助手**：对话式问答与聊天总结（经 LangGraph Agent）、一键同步、历史报告
- **右侧常驻栏**：重要信息 + 随手备忘（多条记录，可与每日任务互相转换）

## 技术栈与结构

- 后端：Python 3.13 + FastAPI + SQLAlchemy + Alembic（SQLite `data/hub.db`）
- 前端：React + TypeScript + Vite + Tailwind + TanStack Query（构建产物由 FastAPI 托管）
- LLM：DashScope（OpenAI 兼容），配置见 `app/wechat_agent/llm_config.json` + `~/.personal-hub/.env`
- 微信模块：`app/wechat_agent/`（由原 LangGraph 项目迁入）

```
app/        FastAPI 后端（api / services / adapters / models / tasks / wechat_agent）
web/        React 前端（npm run build 产物由后端托管）
launcher/   Windows 启动器（.bat / .vbs / launch.py）
data/       运行时数据（hub.db、logs/、reading_notes/），不入 Git
tests/      pytest（隔离临时库，Mock LLM/外网）
Docs/       规划与架构文档（见下）
```

## 启动与使用

1. 安装依赖：Conda 环境 `agent`（Python 3.13，见 `requirements.txt`）；前端 `cd web && npm install && npm run build`
2. 双击 `launcher/个人助手.bat`（或 `python launcher/launch.py`）→ 自动启动服务并打开浏览器
3. 访问 http://127.0.0.1:8620 （端口可用环境变量 `PH_HUB_PORT` 修改）
4. 密钥：在 `~/.personal-hub/.env` 配置 `DASHSCOPE_API_KEY`（键名清单见 `.env.example`）

开发模式：`uvicorn --factory app.main:create_app --reload`；微信 Agent 的命令行问答入口：`python -m app.wechat_agent.agent`。

## 开发

```bash
# 后端测试（隔离数据副本，零真实外网/Token）
python -m pytest
# 前端测试 / 类型检查 / 构建
cd web && npm test && npx tsc --noEmit && npm run build
```

开发规范与约束见 [AGENTS.md](AGENTS.md)（AI 编码助手必读）。

## 文档导航

- [AGENTS.md](AGENTS.md) — 开发规范：架构铁律、数据安全、命名、测试与提交
- [Docs/PRD.md](Docs/PRD.md) — 产品需求与业务规则的权威来源（含 D1–D8 决策）
- [Docs/Architecture.md](Docs/Architecture.md) — 技术架构的权威来源（模块边界、存储设计、接口约定）
- [Docs/DEVELOPMENT_PLAN.md](Docs/DEVELOPMENT_PLAN.md) — 下一阶段开发阶段规划（V1 计划已归档至 [Docs/archive/DEVELOPMENT_PLAN_V1.md](Docs/archive/DEVELOPMENT_PLAN_V1.md)）
- [Docs/ADR/](Docs/ADR/) — 重大技术决策记录（按需创建，当前为空）
