# 24 小时窗口回溯与重大新闻覆盖实测

> 窗口：**2026-11-09 08:00（含）~ 2026-11-10 08:00（不含），北京时间**。
> 测试时刻：2026-11-10 13:34–14:10 CST（回溯已完整结束的窗口，符合任务要求）。
> 脚本：`api_tests/window_collection.py`、`api_tests/coverage_hits.py`；原始证据：`fixtures/`、`results/coverage_hits.json`。

## 1. 各源对固定窗口的语义适配（逐条核对任务书 10 项）

### 1.1 中新网按日归档页（scroll-news/2026/MMdd/news.shtml）——✅ 精确适配

| 检查项 | 结果 |
|---|---|
| 能否精确指定起止 | ✅ 取两个自然日归档页（11-09、11-10），条目自带分钟级北京时间，本地按 `[08:00, 次日08:00)` 过滤 |
| 原始发布时间 | ✅ 每条有 HH:MM 时间戳（编辑发布行为准） |
| 发现时间误当发布时间 | 无（无发现时间字段） |
| 窗口起点附近条目 | ✅ 两日合并后窗口内解析出 **~340 条**（11-09 全天 478 条中 08:00 后 + 11-10 00:00–07:59），起点 08:00 附近条目存在 |
| 分页遗漏 | 归档页单日 478 条一次性在页内（翻页仅 news1.html 一个实时页，归档不分页） |
| 只返回少量精选 | 否，是全量滚动存档 |
| 08:00 失败后重试丢早期内容 | 否——历史归档页不回溯删除（11-09 页在 11-10 14:00 仍完整可取） |
| 发布延迟 | 中新网自己的发稿时间即条目时间，无额外延迟 |
| 需要额外回溯机制 | 不需要；**需要 HTML 解析器**（非官方 API，结构变更即失效） |

### 1.2 热摸爽 /daily + /hot Markdown ——⚠️ 可用但窗口错位 3 小时

- 11-10 早报的统计周期是 **05:00–05:00**（北京时间），发布于 05:31；`/hot/2026-11-10.md` 冻结于 05:00。
- 与晨报窗口的差异：缺 11-10 05:00–08:00 段；多 11-09 05:00–08:00 段（窗口外）。
- 条目**无原始发布时间**（feed 统一生成时间、事件页只有 capturedAt 抓取时间），无法在条目级按 08:00 精确过滤 → 只能接受“05:00 对齐”或按摘要内日期+原站链接粗判。
- 回溯能力优秀：历史日期 MD 永久冻结，08:00 当次请求失败、当日稍后重试不丢内容；`/daily/2026-11-09.md` 实测可取。

### 1.3 中新网 RSS ——❌ 不适配单次 08:00 查询

scroll 仅最近 ~1.5 小时（30 条，04:03–05:29 UTC），world 仅最近 ~8 小时。**无论窗口语义如何，单次查询物理上拿不到 24 小时内容**；每 4 小时采一次RSS也丢 2.5–4 小时。RSS 只能当“最新动态”用。

### 1.4 GDELT —— 窗口语义 ✅（startdatetime/enddatetime），工程稳定性 ⚠️

- 官方 DOC 2.0 支持 `startdatetime/enddatetime`（精确到秒，UTC）；seendate 为 GDELT 标注时间（近似原始发布，存在数分钟~小时级偏差）。
- 实测：48h 中文查询 200（11s）；精确窗口查询遭遇 ReadTimeout/429 重试（`results/gdelt_window.json` 记录全过程）——**API 免费但限流不稳定，需要重试与限速设计**。
- `timespan` 参数为滚动窗口（以请求时刻为锚），**不满足固定 08:00–08:00 语义**，必须换算成 startdatetime/enddatetime。
- 单次最多 75 条/250 条（按模式），窗口内中文报道量远大于上限 → hybridrel 截断；**不能拿返回条数当覆盖指标**。

### 1.5 GNews / BBC / 聚合数据

- GNews：接口支持 publishedAt 过滤，但免费层 **12 小时数据延迟**——每天 08:00 查询结构性缺失窗口最后 1/3；且每次仅 10 条。语义可行、免费层不可用。
- BBC：本机不可达（网络出口），无窗口测试。
- 聚合数据：无 Key，BLOCKED。

## 2. 重大事件覆盖实测

### 2.1 参考清单（人工核实，非由候选 API 生成）

来源：财新、新华社/中新网、路透（经朝日新闻）、澎湃新闻、同花顺转央视、Gulf News 等，交叉核实。清单全文与证据链接：`fixtures/reference_events.json`。

- 国内 4 件：D1 太原火灾（窗口内新进展）、D2 人民币境外清算行试点（重大经济）、D3 统计局新设普查司（政策）、D4 星云星座计划（公共事件）。
- 国际 5 件：I1 特朗普“铁门”行动/APEC 会晤预期、I2 国际油价跌超 5%、I3 俄副外长表态、I4 鲁比奥-黄仁勋事件、I5 霍尔木兹局势。

局限：单日样本、9 件、关键词命中口径；**仅作源间相对比较，不构成长期覆盖保证**。

### 2.2 命中矩阵（关键词命中 + 人工核对匹配条目真实相关）

| 事件 | 中新网归档 | 中新网RSS | 热摸爽早报/快照 | GDELT(中) | GDELT(英) |
|---|---|---|---|---|---|
| D1 太原火灾 | ✅ 18:00/20:00 两条在窗口内 | ❌ | ✅ 第11条（news.cn 源） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| D2 清算行试点 | ❌ | ❌ | ❌ | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| D3 统计局调整 | ❌ | ❌ | ❌ | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| D4 星云星座 | ✅ 16:28 | ✅（13:19 补稿，窗口外时间） | ✅ 第4条 | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| I1 铁门/APEC | ✅ 17:38 | ❌ | ✅ | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| I2 油价跌5% | ❌ | ❌ | ✅ 第18条（news.cn 源） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| I3 俄副外长 | ❌ | ❌ | ✅ 第16条 | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| I4 鲁比奥/黄仁勋 | ✅ 15:23 | ❌ | ✅ 第17条（NYT 源） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| I5 霍尔木兹 | ✅ 21:42 | ❌ | ❌ | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） | 未测（GDELT 多轮间隔重试均 429 限流，见 results/gdelt_window_manual.json / gdelt_window_final.json；窗口语义以官方文档+48h 实测为据） |
| **覆盖率（暂不含 GDELT）** | **国内 2/4、国际 3/5** | 0/9 | **国内 2/4、国际 4/5** | — | — |

要点：
- **中新网归档 + 热摸爽互补性强**：并集覆盖 7/9（D1、D4、I1–I5）；都漏掉的是 D2、D3 两件财新系财经/机构政策新闻——说明**热点型源对低频政策经济信号系统性不敏感**，这是“每日聚合”方案的固有盲区。
- 热摸爽偏社交平台热点，中新网偏通稿；两者都没有财新类深度财经源。
- 中新网的 D4 命中是 11-10 13:19 的补稿（窗口外），归档时间戳使这类错位可被发现；热摸爽条目无时间戳，同类错位不可发现（只能靠原站链接日期）。
- GDELT 两列待 `results/gdelt_window.json` 补测后回填。

### 2.3 重复、无关与可追溯

- 热摸爽早报同一事件可出现两次（I4：独立条目 + “8点1氪”合集），需要事件级去重（T20 分层去重可覆盖）。
- 中新网归档 ~340 条窗口条目绝大多数为常规通稿，重大事件筛选仍需自建重要性排序（与 GDELT 相同的工程问题）。
- 原始链接可追溯率：热摸爽 100%（条目直链原站）、中新网 100%；但**本机 news.cn、caixin.com、cn.nytimes.com 不可达**，回溯正文核查不可全源保障（m.thepaper.cn、10jqka、qbitai 等可达）。

## 3. 时效差异（事件发布 vs 接口可发现）

| 事件 | 参考发布时间 | 中新网归档 | 热摸爽（05:00 快照/05:31 早报） |
|---|---|---|---|
| D1 通报 | 11-09 白天 | 18:00（同日晚间） | 11-10 05:31 早报（T+约半日） |
| D4 发布 | 11-09 白天 | 16:28 | 11-10 05:31 早报 |
| I1 铁门 | 11-09（路透 14:45 JST） | 17:38 | 11-10 05:31 早报 |
| I4 NYT | 11-09 | 15:23 | 11-10 05:31 早报 |

热摸爽早报固定 T+到次日 05:31 才能读，**08:00 查询时延迟 ~2.5–26 小时**（取决于事件发生时刻）；中新网归档当日可得。GDELT seendate 通常分钟级~小时级。


