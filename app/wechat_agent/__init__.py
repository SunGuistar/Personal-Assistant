"""微信 Agent 模块（阶段 3.2 自 LangGraph/ GetWechatInfo/ Tool/ 迁入）。

目录结构：
- agent.py / llm_config.py(.json)：Agent 装配与 LLM 配置
- chat_tools/：只读查询工具与总结流水线
- normal_tools/：chunking、rag_store、report_render 等
- data_api/：WeChatDataAnalysis 客户端与消息快照库
- structured/：消息归一化

聊天数据仍位于 GetWechatInfo/DataInfo/（真实数据原地保留）。
"""
