# MCP vs REST API 对比（mcp_vs_rest）

> 对象：天聚数行（唯一同时提供 REST 与 MCP 且国际新闻可达的候选）。聚合数据平台有 MCP 入口但每日简报接口本身的 MCP 接入未在文档中给出（导航栏有 MCP 频道，接口级配置未提供 → 不视为可用 MCP 证据）。

## 1. 实测事实（LIVE + STATIC）

| 项 | 结果 | 证据 |
|---|---|---|
| MCP Server 是否可连接 | 端点真实存在：`https://mcp.tianapi.com/allnews/index?key={apiKey}`，无 Key 返回 HTTP 400 `Invalid API key`（application/json，62ms） | LIVE 探测 |
| 接入方式 | 远程 HTTP MCP（URL 内嵌 Key 鉴权），**无需本地常驻进程/额外依赖** | STATIC（文档 MCP 配置段） |
| 鉴权 | 与 REST 同一个 apiKey，URL query 传参 | STATIC + LIVE（错误提示一致） |
| 底层数据 | MCP 由"分类新闻"接口统一提供；返回字段与 REST 完全一致（id/url/ctime/title/source/description） | STATIC（apiview/51 与 apiview/5 字段同构；[官方 MCP 指南](https://www.tianapi.com/article/213)） |
| 额外调用费用 | 无（共用会员免费额度，100 次/天免费层） | STATIC |
| 国际新闻查询 | 分类新闻 col 参数含国际频道（频道 ID 表文档可查） | STATIC |

## 2. 对当前系统（FastAPI + LangGraph）的适配比较

| 维度 | 定时任务直连 REST | Agent 经 MCP Tool 调用 |
|---|---|---|
| 确定性 | 高：请求参数、分页、过滤完全代码控制 | 低：Tool 调用由 Agent 决定，结果需再校验 |
| 稳定性 | 高：普通 HTTP 请求，超时/重试/退避按既有 tasks 状态机规范实现 | 中：多一层 MCP 协议栈，故障面更大 |
| 可测试性 | 高：可直接用 respx 等 mock | 低：需 mock MCP server |
| 可复现 | 高：固定参数固定结果 | 低：Agent 行为有随机性 |
| 数据结构 | 相同（同一份数据） | 相同 |
| 额外能力 | 无 | **无**（MCP 未提供 REST 之外的参数或数据） |

## 3. 结论

**MCP 只是将同一批 REST 接口包装为 Agent Tool，不是新增独立数据源**（任务书预置判断得到证实）。对"每天 08:00 固定窗口查询"这种确定性批处理任务，REST API 全面优于 MCP；本系统也不存在"只有 MCP 才能拿到的数据"。

**建议：采用 REST API。** MCP 仅在以下情况重新考虑：未来需要让晨报 Agent 在对话中按需临时查新闻（开放式追问属 V3 规划），届时再评估。
