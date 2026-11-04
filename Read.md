# Personal Hub

基于本地优先原则的个人信息与事务管理平台（Windows）。当前为 V1.0 开发中：阶段 1（基础框架）、阶段 2（计划/阅读管理）、阶段 3（微信 Agent 集成）已完成开发，等待人工验收。

## 启动

双击 `launcher/start_hub.bat`（或命令行运行 `python launcher/launch.py`），浏览器自动打开 http://127.0.0.1:8620 。

## 功能

- **计划管理**：长期计划 + 每日任务（勾选/排序/移至其他日期/进度统计）
- **阅读管理**：书籍与阅读状态、云记导出笔记（PDF/PNG）上传与在线预览
- **微信聊天助手**：对话式问答与聊天总结（需 WeChatDataAnalysis 运行于本机 10392 端口）、聊天同步、历史报告

## 开发

- 环境：Conda `agent`（Python 3.13）；前端 `cd web && npm install && npm run build`
- 后端测试：`python -m pytest`（隔离数据副本，真实聊天库零写入）
- 前端测试：`cd web && npx vitest run`
- 规范与规划：见 `AGENTS.md` 与 `Docs/`（PRD / ARCHITECTURE / DEVELOPMENT_PLAN / TEST_PLAN / ROADMAP）

## 备注

原微信总结 Agent 的 REPL 入口已迁移至 `app/wechat_agent/`，可在仓库根目录以
`python -m app.wechat_agent.agent` 独立运行（命令行问答模式，行为不变）。
