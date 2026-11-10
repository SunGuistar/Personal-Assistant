# 候选 API 对比（api_comparison）

> 证据分级：LIVE = 本机真实请求；STATIC = 官方文档快照（`fixtures/*_doc.html`）。实测时间 2026-11-10 14:17–14:40 CST。
> 环境中未配置任何候选服务的 Key（已扫描 `~/.personal-hub/.env` 键名，无 tianapi/juhe/itapi 相关项；未输出任何密钥值）。

## 1. 探测结果总表

| 候选 | 端点 | 探测（LIVE） | 状态码/耗时 | 需 Key | 数据实测 |
|---|---|---|---|---|---|
| 天聚数行 国际新闻 | `https://apis.tianapi.com/world/index` | `{"code":240,"msg":"缺少API密钥参数"}` | HTTP 200 / 0.52s / application-json | 是 | BLOCKED |
| 天聚数行 每日简报 | `https://apis.tianapi.com/bulletin/index` | `{"code":240,...}` | HTTP 200 / 0.10s | 是 | BLOCKED |
| 天聚数行 分类新闻（MCP 主体） | `https://apis.tianapi.com/allnews/index` | 文档确认（STATIC） | — | 是 | BLOCKED |
| 聚合数据 每日简报 | `https://apis.juhe.cn/fapigx/bulletin/query` | `{"reason":"错误的请求KEY","error_code":10001}` | HTTP 200 / 0.19s | 是 | BLOCKED |
| 顺为数据 综合新闻 | `https://api.itapi.cn/api/news/news` | `{"code":403,"msg":"请求密钥KEY不正确！...免费申请"}` | HTTP 200 / 0.26s | 是 | BLOCKED |
| 中新网国际归档 | `https://www.chinanews.com.cn/scroll-news/{YYYY}/{MMDD}/news.shtml` | 两日均 HTTP 200，475+175 条可解析 | 0.5–1.3s / text-html | 否 | **PASS（LIVE）** |

所有 Key 类接口的无 Key 探测返回的都是**结构化业务错误**而非 404/超时 → 端点真实存在且服务正常；真正的新闻数据字段、时效与覆盖因无 Key 全部 BLOCKED，不做任何推测性填充。

## 2. 天聚数行 world/index（国际新闻）——STATIC 文档核查

来源：`fixtures/tianapi_world_doc.html`（https://www.tianapi.com/apiview/5，2026-11-10 快照）。

- 接口有效，返回 utf-8 JSON；字段：`id / url / ctime(发布时间,分钟级) / title / picUrl / source / description(摘要,可为空)`；`allnum / curpage` 支持翻页；`num` 1–50；`word` 关键词搜索。
- **无按发布时间过滤/查询历史窗口的参数**（只有"最新 N 条 + page + word"）。要覆盖"前一天 08:00–当天 08:00 全部候选"，只能在 08:00 翻页拉取足够条数后按 `ctime` 本地过滤；API 不保证窗口早期内容仍可翻页到（`allnum` 语义为总结果数，滚动新闻场景下分页深翻的稳定性未实测，BLOCKED）。
- 更新频率：文档未给出；`ctime` 是发布时间还是采集时间无法在 STATIC 层面区分，实测 BLOCKED。
- 免费额度：普通会员免费，100 次/天、QPS 3、免费接口限 10 个。每天 08:00 一次查询消耗 1–5 次额度，**额度本身足够**。
- **授权（关键）**：文档原文"本接口仅限用于内部数据分析和机器学习，**不得用于终端展示**。版权问题请联系发布方获取。"
- 注册要求：需注册账号、申请接口、获取 API Key（需手机/邮箱注册，任务书禁止代注册）。

### 私人晨报是否属于"终端展示"？

不能直接认定。两种解读：
1. **宽松解读**：晨报是个人内部阅读物，不对公众分发，类似"个人终端"，可能不在禁止范围。
2. **严格解读**：晨报以 HTML 页面形式呈现新闻标题+摘要+链接，本质就是终端展示；且"生成摘要再利用"叠加新闻版权（来源为中华网等媒体），授权链不完整。

**结论：授权存在实质不确定性，必须由用户阅读条款后决定，或由用户向官方确认；验证方不自行认定获得授权。** 这是该源的上线前置阻塞项。

## 3. 聚合数据 每日简报（fapigx/bulletin/query）——STATIC 文档核查

来源：`fixtures/juhe_742_doc.html`（https://www.juhe.cn/docs/api/id/742）。

- 接口有效（LIVE 探测返回标准错误 JSON）。字段仅三样：`mtime`（**日期级**，如 "2023-02-07"）、`title`、`digest`（编辑整理的一段简报）。
- **无原始链接、无来源名、无逐条发布时间、无分页、无历史日期参数**（文档示例即当日简报列表）。
- 文档自述"digest 字段是一段概括性的简报摘要，适合应用于每日简报类应用场景"。
- 每日更新时点、更新前是否覆盖完整前一日：STATIC 无法确认，实测 BLOCKED。

### 角色判定

**不能做主新闻源**：无 URL 无法追溯原文、无逐条时间无法进 08:00 窗口过滤、无来源无法事实核查、国际/国内不可区分（需实测确认，BLOCKED）。
**可以做"重要新闻覆盖检查"**：把当日简报标题与晨报已选国际条目比对，发现"简报有而晨报没有"的潜在漏报，作为发布前事实校验的辅助信号（类似 D01 中 GDELT 的角色）。
授权条款需注册后可见，BLOCKED。

## 4. 天聚数行 每日简报（bulletin/index）+ MCP

来源：`fixtures/tianapi_bulletin_doc.html`（apiview/117）。

- REST 返回字段：`mtime`（日期级）、`title`、`digest`——**与聚合数据简报同构**，同样无 URL/来源/逐条时间。适合做覆盖检查，不适合做主源。
- **MCP 为真实提供**：分类新闻 MCP 地址 `https://mcp.tianapi.com/allnews/index?key={apiKey}`（STATIC 文档），LIVE 探测无 Key 返回 HTTP 400 `Invalid API key`（application/json）→ 端点存在、鉴权为 URL 内嵌 Key。新闻类接口统一由"分类新闻"这一个 MCP 服务提供（[官方 MCP 配置指南](https://www.tianapi.com/article/213)）。
- MCP 是远程 HTTP MCP（streamable），无需本地常驻进程；鉴权即 Key；底层与 REST 同一份数据（字段完全一致）→ **MCP 不是新增独立数据源**，详见 `mcp_vs_rest.md`。

## 5. 顺为数据 综合新闻（itapi.cn，备选）

来源：`fixtures/itapi_83_doc.html`（https://api.itapi.cn/doc/83）。

- 端点 `https://api.itapi.cn/api/news/news`，需 Key（LIVE 探测：HTTP 200 `{"code":403,"msg":"请求密钥KEY不正确！...免费申请"}`，响应耗时 0.26s，返回 `log_id`）。
- 文档显示参数：`page`、`num`（20–100，默认 20）、`type=channel` 取分类值。字段结构文档未完整展示示例响应（示例代码为主），**时间字段、国际分类、许可条款均无法从文档确认**。
- 免费申请 Key（文档明示免费），但任务书禁止代注册 → BLOCKED。
- 因主要候选（中新网归档）已实测通过，按任务书"必须说明为什么有必要增加"：目前**没有必要**为其额外注册。

## 6. 中新网国际归档（复用验证，LIVE）

详见 `coverage_analysis.md` 与 `results/chinanews_world_window.json`。要点：

- 国际栏目有稳定分类标识（`dd_lm` 栏目链接 + `/gj/` 路径），归档页结构 `div.dd_lm / dd_bt / dd_time` 两轮实测一致。
- 窗口 2026-11-09 08:00 ~ 11-10 08:00：**全栏目 477 条、国际栏目 44 条**，最早 08:02、最晚 07:42，分钟级时间戳，跨两天归档页拼接完整。
- 抓取时间为 11-10 14:24（窗口结束后 6 小时）→ **任何时刻重取都不丢窗口内容**（冻结内容），08:00 失败 09:00 重试无损失。
- robots/使用条款：中新网无公开 API 条款；归档页为公开页面，低频抓取（每天 2 页）风险低但需自担结构变更与合规责任（与上一轮结论一致）。
