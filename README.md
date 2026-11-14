# 个人助手（Personal Hub）

运行在 Windows 本地的个人信息与事务管理平台：FastAPI 后端 + React 前端，浏览器访问，本地优先、单用户。**当前版本仅面向 PC 浏览器**。

**核心定位：个人数据驱动的智能工作助手**——整合计划、备忘、重要信息、阅读记录及未来接入的 GitHub 等个人数据，利用 AI 进行信息整理、关联分析、总结和建议（规划见 `Docs/DEVELOPMENT_PLAN.md`）。

当前开发方向（仅规划，均未实现）：GitHub 数据集成（REST API）→ 每日工作简报 → 长期记忆 → Agent 工程能力增强。

## 主要功能

- **首页工作台**：今日计划、正在读的书、系统状态一览
- **计划管理**：长期计划（重要置顶、标记完成、历史、具体目标）与每日任务（今日/逾期统一排序、历史只读）；两模块完全独立
- **阅读管理**：书籍与阅读状态、重要标记、云记导出笔记（PDF/PNG）上传与在线预览
- **微信聊天助手**：对话式问答与聊天总结（经 LangGraph Agent）、一键同步、历史报告
- **GitHub 数据**：REST API 同步仓库/Commit/PR/Issue，GitHub 风格年度贡献热力图（悬停/日详情/年份切换）
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
2. 双击 `launcher/个人助手.bat`（或 `python launcher/launch.py`）→ 浏览器显示启动页 → 计划管理首页就绪后自动进入
3. V2 默认访问 http://127.0.0.1:8621；启动、停止、重启统一读取 `launcher/launcher.ini` 的 `server.port`，更换端口只需修改该处
4. 密钥：在 `~/.personal-hub/.env` 配置 `DASHSCOPE_API_KEY`（键名清单见 `.env.example`）

开发模式：`uvicorn --factory app.main:create_app --reload`；微信 Agent 的命令行问答入口：`python -m app.wechat_agent.agent`。

日常管理：双击 `launcher/停止个人助手.bat` 结束后端，双击 `launcher/重启个人助手.bat` 先停止再启动；关闭浏览器不会停止后端。也可运行 `python launcher/launch.py --action stop` 或 `--action restart`。操作失败会弹窗提示，详情见 `launcher/logs/launcher.log`。停止或重启会中断正在执行的任务。

启动与重启会在 Python 启动器就绪后先打开浏览器启动页，显示当前阶段、阶段耗时及累计等待时间；计划管理首页就绪后，同一标签页自动进入首页。晨报、微信管理、阅读和 GitHub 在后台初始化；导航切换到尚未就绪的模块时显示“加载中”，就绪后自动展示内容，失败则显示明确提示。首页中的晨报和清理提醒也会等对应模块就绪后再查询。关闭启动页不会停止后端，临时启动页服务在结果送达或超时后退出。

`launcher/logs/launcher.log` 保存启动器流程，`startup-*.jsonl` 保存各次后端阶段记录（含后台模块），`uvicorn.log` 保存后端进程输出。总耗时包含进入 Python 前的启动脚本/Conda 引导估算（秒精度），首页计时终点为健康检查通过，不包含浏览器页面渲染；其他阶段使用单调时钟，父阶段含子阶段，不可相加。命令行 `--no-browser` 不打开启动页，`--progress` 可额外显示原诊断窗口。

停止前会核验监听进程的应用入口及工作区路径，拒绝停止其他工作区或无法核验的进程。升级前启动的旧进程没有工作区标识，需要手动停止一次，之后通过上述入口启动即可使用一键停止/重启。

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
