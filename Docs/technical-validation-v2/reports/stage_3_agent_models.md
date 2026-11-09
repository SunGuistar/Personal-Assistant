# 阶段三报告：Agent 框架与模型调用验证（T8、T15、T21 集成面）

## T8（PARTIAL：STATIC 充分，LIVE 部分受阻）

官方文档核查（api-docs.deepseek.com，2026-11-08 抓取）：

- **DeepSeek-V4.1-Flash-1017 真实存在**，但它是"模型版本名"；公开 API 模型标识是 **`deepseek-flash`**（旧名 deepseek-v4-flash 仍接受，后端即 V4.1-Flash-1017）。产品文档已写明"实际 API 标识由 Kimi Code 核实"——结论：调用时传 `deepseek-flash`。
- **低峰时段**（官方口径）：周一至周五（不含中国法定节假日）UTC 01:00–04:00、06:00–10:00 为高峰（=北京 09:00–12:00、14:00–18:00），其余为低谷，低谷价=高峰价一半；周末与节假日全天低谷。**每天 08:00（北京）= 低谷**，自动生成在价格窗口内。
- deepseek-flash 支持 JSON Output、Tool Calls、Responses API、Vision、1M 上下文。
- 低谷检查函数 6 项断言（含跨时区输入）全过。
- **受阻项**：`DEEPSEEK_API_KEY` 未配置 → DeepSeek 真实调用 BLOCKED（未消耗任何费用）。配置后需补：/models 列表、1 次 chat 验证、prompt_cache_hit_tokens 观测。
- **DashScope（LIVE）**：`qwen3-vl-plus` 与 `qwen-flash` 经 **OpenAI 兼容端点**调用成功（200）；`qwen-plus` 返回 403 FreeTierOnly（免费额度耗尽）；dashscope 旧版 SDK 端点对 vl 模型报 400（url error）——**新代码应统一走兼容端点**（langchain-openai ChatOpenAI 直接可用）。质量评价的独立调用路径验证可行。

## T15（PASS，SIMULATION）

最小 LangGraph 工作流（prepare → 并行普通节点 → 并行技术研究/目标分析 → 后置建议 → 主编 → 校验 → 终态）实测：

- 并行节点窗口相交（真并行，非表面并行）；状态合并正确。
- 三个 Subagent 用 `langchain.agents.create_agent` 构建，图内并行与串行均实际触发了共享的统一 RAG Tool（`run2_via: create_agent`）。
- 建议节点断言在前两者 end 事件之后启动（通过）。
- AsyncSqliteSaver Checkpoint：goal_analysis 注入失败 → 抛出 → 修复后 `invoke(None)` 恢复，goal 标 success，报告 verified。
- 恢复语义注意：**与失败节点同 super-step 的已完成节点会被重跑**（LangGraph 语义，需在设计阶段缓存时考虑，避免重复计费）。
- 未使用 Deep Agents。

实施教训（本轮排障所得，已写入最终报告）：LangChain `BaseMessage.type` 取值是 `human` 不是 `user`；GenericFakeChatModel 的 messages 迭代器不可共享；create_agent 在异步父图内须用 ainvoke（sync invoke 会触发 AsyncSqliteSaver 同步检查错误）。

## T21 的 Agent 集成面

三个 Subagent 共享同一 RAG Tool 定义已在 T15 工作流内验证（工具调用、来源返回）；按需改写/重排的开关组合在 T21 四模式验证。

## 是否可以继续

可以。模型侧待办只有一件：**申请/配置 DEEPSEEK_API_KEY 并补 1–2 次真实调用**（可选：DeepSeek 新用户有赠送额度）。
