# 阶段一报告：数据来源与采集验证（T1–T7、T11、T19、T20）

> 日期：2026-11-08。证据：`results/*.json`；脚本：`probes/*.py`；样本：`fixtures/`。
> 网络环境说明：本机直连国内网络，无代理。国内站点多数可达；feeds.bbci.co.uk、api.newsapi.org、aihot.cn 等不可达（DNS/连接失败，证据见结果 JSON）。

## 测试了什么（真实组件 vs Mock）

- **真实**：hub.db 只读审计（T1）、GDELT/中新网/百度/知乎/HN/github.blog/hotai.news/daily.dev 实际 HTTP 请求（T2–T5、T11）、DashScope Embedding（T20 语义归组）、APScheduler 实际调度（T19，.venv-probe）。
- **Mock/模拟**：T7 可控时钟与模拟新闻源；T6/T20 的转载样本为人工 fixture；T20 的 TF-IDF 归组为语义代理。

## 关键发现

1. **个人数据可还原性（T1，PARTIAL）**：`daily_tasks.completed_at` 是真实的完成时间证据（34 条完成中 12 条完成时间≠任务日，说明不是摆设）；只读窗口查询可行。但完成时间单值覆盖（取消再完成会丢历史），memos/重要信息/阅读无完成语义。→ 晨报模块需自建只读事件快照（每日任务完成/取消完成、计划状态变化），不改原库。
2. **国内源（T2，PARTIAL）**：GDELT v2（中文、48h、JSON、免费）+ 中新网 RSS 可用；均无正文，需回溯原站。重大公共新闻覆盖可用 GDELT 中文源验证（样本含进博会、政策类）。
3. **国际源（T3，BLOCKED）**：BBC/CNN/AlJazeera RSS 本机不可达。属网络出口问题，非技术不可行。需要用户解决网络（代理）或换可达源。
4. **AI 源（T4/T5，BLOCKED/PARTIAL）**：AIHOT 三个域名均不可达/证书异常，其"热度"语义无法核实——按产品要求不做解释性猜测。hotai.news 可达且分区清晰；daily.dev 端点通但公开查询失效；HN 与 github.blog RSS 稳定可用。
5. **NewsAPI（T11，BLOCKED）**：网络不可达 + 无 key。官方文档口径：开发者版 100 次/天、限非商用开发环境、正文仅 ~200 字符。即便有 key，"六个时点各调用一次"在量上没问题，但免费层不可用于生产。
6. **08:00 快照（T7，PASS）**：全部 7 项检查通过。重要实测：**快照若不隔离，后台更新会静默污染快照**——必须快照隔离（内容哈希清单）。
7. **调度（T19，PASS）**：APScheduler CronTrigger 六个时点计算准确；max_instances=1 实测并发=1；SQLite jobstore 重启保留任务；时区 Asia/Shanghai 无 DST 问题。
8. **分层去重（T20，PASS）**：三层（精确哈希/simhash+MinHash/Embedding 语义）在 14 篇覆盖 10 类场景的样本上：无误合并；同事件保守归组（宁可漏合）；新进展/新版本/纠正样本全部保留。真实 Embedding 调用 4 次。

## 是否可以继续

可以。采集侧最小可行组合：**国内=GDELT+中新网 RSS；国际=待网络解决（BBC 或替代）；AI=hotai.news+HN+GitHub Blog+官方博客 RSS**。T3/T4/T11 的 BLOCKED 均属网络/凭据类，不推翻架构。

## 对后续开发的影响

- 晨报 SQLite 需 `news` 表支持 content_hash、event_id、来源、发布/采集时间与缺失标记。
- 分层去重阈值是初值，需用真实数据回归。
- 调度器直接引入 APScheduler（项目当前无调度器先例）。
