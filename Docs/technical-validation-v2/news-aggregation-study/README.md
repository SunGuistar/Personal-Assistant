# 新闻聚合 API 专项验证（news-aggregation-study）

> 轮次：今日晨报 V2.0 国内/国际新闻“每日 08:00 聚合查询”可行性专项验证。
> 日期：2026-11-10（Asia/Shanghai）；执行环境：Windows + Conda `agent`（Python 3.13.18），本机直连国内网络、无代理。
> 结论先看：**FINAL_RECOMMENDATION.md**（国内=有条件可以取消四小时采集；国际=不建议；方案 D 折中）。

## 验证问题

能否通过一个或多个现成新闻聚合 API/RSS，每天 08:00 一次性获得足够完整、及时、可信的国内和国际重大新闻，从而取消每四小时采集？本轮只验证、不实施。

## 目录结构

```text
news-aggregation-study/
├── README.md                     ← 本文件
├── source_comparison.md          ← 候选来源逐源实测对比（可用性/字段/窗口语义/授权）
├── coverage_analysis.md          ← 24h 窗口回溯测试 + 重大事件覆盖实测
├── FINAL_RECOMMENDATION.md       ← 最终建议（含 A/B/C/D 比较、人工复核指南）
├── api_tests/                    ← 可复跑隔离脚本（未改任何正式业务代码）
│   ├── probe_availability.py     ← 全候选源连通性/状态码/耗时
│   ├── probe_remoshuang.py       ← 热摸爽结构探针（榜单/RSS/feed.xml）
│   ├── window_collection.py      ← 24h 固定窗口采集（chinanews RSS/GDELT/remoshuang）
│   ├── gdelt_window_retry.py     ← GDELT 精确窗口重试（本轮遇限流）
│   └── coverage_hits.py          ← 参考事件×候选源 命中测量
├── fixtures/                     ← 原始响应与人工参考清单（证据）
│   ├── reference_events.json     ← 人工核实的 9 件重大事件（含独立证据链接）
│   ├── chinanews_*.{xml,html}    ← 中新网 RSS 与按日归档页原件
│   ├── remoshuang_*.{md,xml,html}← 热摸爽早报/快照/RSS/Agent指南原件
│   └── gdelt_*                   ← GDELT 响应（含限流 429 原文）
└── results/                      ← 结构化结果 JSON
    ├── availability.json         ← 各源 HTTP 级证据
    ├── remoshuang_structure.json ← 热摸爽页面/路径探测
    ├── window_collection.json    ← 窗口采集统计
    ├── gdelt_window_manual.json / gdelt_window_final.json ← GDELT 限流证据
    ├── coverage_hits.json        ← 命中矩阵明细
    └── data_quality_notes.json   ← 数据质量抽查记录
```

## 与上一轮（T1–T22）的关系

- 复用：T2（GDELT/中新网 RSS 基础可用性）、T3（BBC 不可达，本轮复测仍失败）、T11（NewsAPI 不可达）、T7/T19/T20（快照/调度/去重结论不变）。
- 本轮新增：热摸爽全量探针、中新网按日归档页发现与验证、GNews 免费层文档核查、聚合数据 BLOCKED 标记、固定 08:00–08:00 窗口回溯测试、人工参考清单覆盖测量、GDELT 限流实测。
- 未覆盖项（如实记录）：GDELT 窗口内文章数据因持续 429 未取到；聚合数据/GNews 无 Key 未真实调用；覆盖率为单日样本。

## 重跑

```bash
cd Docs/technical-validation-v2/news-aggregation-study
PY=D:/miniconda/envs/agent/python.exe
$PY api_tests/probe_availability.py
$PY api_tests/probe_remoshuang.py
$PY api_tests/window_collection.py
$PY api_tests/coverage_hits.py
```

约束遵守：未修改 V0.5/执行流程/D01、未改正式代码与数据库、未装常驻服务、未配代理、未购买套餐、未记录任何密钥（全部请求无 Key）。
