一、项目定位
项目名称： WeChat Agent——基于 LangGraph 的微信聊天智能问答系统

核心目标： 用户通过自然语言自由提问，LangGraph Agent 根据问题自主调用工具，获取微信聊天记录，并利用 LLM 进行总结、分析和回答。

二、使用方式
1.交互式问答：
  `python LangGraph/agent.py`
  进入对话循环，可多轮追问（历史自动带入）；输入 exit / quit 或 Ctrl+C 退出。
2.单轮提问（脚本化调用，答完即退）：
  `python LangGraph/agent.py "总结2026-10-27这个群的聊天"`
  `python LangGraph/agent.py "2026-10-27 这个群聊中，是否有人表达过对主播的担忧？如果有，请找出并总结相关聊天记录，同时列出参与讨论最多的几个人。"`
