# 国际新闻国内 API / MCP 专项验证（international-domestic-api-study）

> 日期：2026-11-10；执行：V2 工作区（`E:/wechat-LangGraph-v2`，分支 `feature/V2`）；环境：Conda `agent`（Python 3.13），Windows，本机直连国内网络无代理。
> 任务来源：《今日晨报 V2.0 国际新闻国内 API / MCP 专项验证》任务书。
> 本轮未修改：V0.5 产品设计、完整执行流程 V1.3、D01（本仓库不存在该文件）、正式代码、正式数据库、正式环境变量、上一轮 news-aggregation-study 的任何结果。
> 前序结论见 `../news-aggregation-study/FINAL_RECOMMENDATION.md`（2026-11-10）：国际新闻免费源不足，BBC 本机不可达，GDELT 限流不稳，GNews 免费层 12h 延迟；国际不建议取消四小时采集（当时结论）。本轮在其基础上研究"国内 API/MCP 获取国际新闻"的替代路线。

## 目录

| 文件 | 内容 |
|---|---|
| `README.md` | 本文件：范围、方法、证据分级总览 |
| `api_comparison.md` | 四个国内 API 候选的逐项对比（含 LIVE/STATIC 证据） |
| `coverage_analysis.md` | 国际重大新闻覆盖率测量方法与结果 |
| `mcp_vs_rest.md` | 天聚数行 MCP 与 REST API 对比 |
| `FINAL_RECOMMENDATION.md` | 最终结论与 12 项必答问题 |
| `probes/` | 可复跑验证脚本 |
| `fixtures/` | 原始响应/文档快照 |
| `results/` | 结构化测量结果 |

## 候选与结论速览（PASS / PARTIAL / FAIL / BLOCKED）

| 候选 | 端点有效 | 数据实测 | 窗口覆盖 | 授权可用性 | 总评 |
|---|---|---|---|---|---|
| 天聚数行 world/index（国际新闻） | LIVE ✅（无 Key 返回 code 240） | **BLOCKED**（需注册 Key） | 未知（文档称仅"最新 N 条+翻页"，无时间过滤参数） | ⚠️ 官方明示"仅限内部数据分析和机器学习，**不得用于终端展示**" | **BLOCKED（授权待用户确认）** |
| 聚合数据 每日简报（fapigx/bulletin） | LIVE ✅（无 Key 返回"错误的请求KEY"） | **BLOCKED**（需 Key） | 不可用：mtime 仅日期级、无 URL、无来源、无逐条时间 | 未知（需注册后见条款） | **BLOCKED**；结构上只能做"重要新闻覆盖检查"，不能做主源 |
| 天聚数行 每日简报（bulletin/index）+ MCP | LIVE ✅（MCP 端点真实存在） | **BLOCKED**（需 Key） | 同上：仅日期级 mtime，无 URL/来源 | 同上授权限制 | **BLOCKED**；MCP 确认为同一 REST 数据的包装 |
| 中新网国际归档（按日归档页） | LIVE ✅ | LIVE ✅（本目录实测） | **PASS**（44 条国际/窗口，分钟级时间戳，跨两天拼接完整） | 无公开 API 条款，归档页抓取自担合规风险 | **PASS**（唯一实测通过的国际窗口源） |
| 顺为数据 综合新闻（itapi.cn） | LIVE ✅（无 Key 返回 403） | **BLOCKED**（需 Key） | 未知 | 未知 | **BLOCKED** |

## 证据分级声明

- **LIVE**：本机真实网络请求的真实响应（存 `fixtures/` + `results/`）。
- **STATIC**：官方文档页面快照（存 `fixtures/*_doc.html`），不等于实测数据。
- **BLOCKED**：缺少有效凭据（Key），按任务书规则不注册、不购买、不虚构响应，该项标记 BLOCKED。
- 接口 HTTP 200 ≠ 验证通过：所有 Key 类接口虽返回结构化错误（证明端点存在），但新闻数据本身的时效、覆盖、字段质量均未能实测。

## 复跑方法

```bash
cd Docs/technical-validation-v2/international-domestic-api-study
PY=D:/miniconda/envs/agent/python.exe
$PY probes/chinanews_world_archive.py   # 中新网国际归档窗口提取（LIVE）
$PY probes/coverage_hits.py             # 参考事件命中率（STATIC fixtures + LIVE 归档缓存）
# 无 Key 端点探测（LIVE，全部不需要凭据）：
curl -s "https://apis.tianapi.com/world/index"          # → {"code":240,"msg":"缺少API密钥参数"}
curl -s "https://apis.tianapi.com/bulletin/index"       # → 同上
curl -s "https://apis.juhe.cn/fapigx/bulletin/query"    # → 错误的请求KEY
curl -s "https://api.itapi.cn/api/news/news"            # → 请求密钥KEY不正确
curl -s "https://mcp.tianapi.com/allnews/index"         # → Invalid API key (HTTP 400)
```

若用户日后提供天聚/聚合 Key，复测清单见 `FINAL_RECOMMENDATION.md` §11。
