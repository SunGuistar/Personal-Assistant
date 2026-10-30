一、项目定位
项目名称： WeChat Agent——基于 LangGraph 的微信聊天智能问答系统

核心目标： 用户通过自然语言自由提问，LangGraph Agent 根据问题自主调用工具，获取微信聊天记录，并利用 LLM 进行总结、分析和回答。

三、运行方式（LangGraph/agent.py）

1. 前置条件
- 依赖安装：`pip install -r requirements_full.txt`（langchain / langgraph / langchain-openai / python-dotenv 等）。
- 在仓库根目录 `.env` 中配置阿里云 DashScope Key：
  `DASHSCOPE_API_KEY=sk-xxx`
  Agent 使用 `ChatOpenAI` 以 OpenAI 兼容模式调用 `qwen-plus`，无需 OpenAI Key。
- 聊天数据：需要归一化聊天库 `GetWechatInfo/DataInfo/chat_snapshot_normalized.sqlite3`
  （已随仓库提供）。如需指向其他库，用环境变量 `WECHAT_AGENT_DB` 覆盖路径。
  所有工具以 SQLite `mode=ro` 物理只读打开，Agent 只分析、不修改数据。

2. 启动命令（在仓库根目录执行）
- 交互式问答：
  `python LangGraph/agent.py`
  进入对话循环，可多轮追问（历史自动带入）；输入 exit / quit 或 Ctrl+C 退出。
- 单轮提问（脚本化调用，答完即退）：
  `python LangGraph/agent.py "总结2026-10-27这个群的聊天"`
- 关闭 Token 消耗打印（默认开启）：
  `python LangGraph/agent.py --no-tokens`

3. 可选：接入 LangSmith 追踪
在 `.env` 中追加：
```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=wechat-chat-summary
```
无需改代码，每次 invoke 的 LLM/工具调用链会自动上报到 LangSmith 控制台。
