# 阶段二报告：数据存储、Qdrant 与 RAG 验证（T9、T12、T13、T14、T21、T22）

> 日期：2026-11-08。Qdrant：Docker 容器 tv2-qdrant（qdrant/qdrant 1.20.0，端口 8633，专用 volume）。

## 真实组件 vs Mock

- **真实**：Qdrant Server（Docker）、DashScope text-embedding-v4（LIVE）、DashScope qwen-flash（T21 改写，LIVE）、rank_bm25（客户端 BM25）、langchain 分词分块、隔离 SQLite。
- **Mock/代理**：T21 Rerank 的 gte-rerank 调用未通过（模型名/权限），用 BM25 代理重排（结果 JSON 中 `rerank_live: false` 已标注）；T14 故障场景为注入。

## 各项结果

- **T12（PASS，LIVE）**：Windows + Docker Desktop（位于 D:\Docker，验证时需先启动）可稳定运行 Qdrant；持久化、重启保留、kill 后已确认写入不丢均实测通过。快照备份可用，但 **file:// recover 在 1.20 返回 404，可用路径是 download + multipart upload**（脚本已用此方式验证恢复 4/4 点）。
- **T13（PASS，INTEGRATION，真实 Embedding）**：dense + 客户端 BM25 + RRF 混合召回对中英文查询均命中；发布时间/来源/晨报日期/version_id 过滤全部正确；2025 年旧晨报可检索（不会因年代被排除）；payload 带 title/source 可回溯。
- **T9（PASS）**：长文分块、全文入 Qdrant payload、语义单元带 version_id、增量更新（旧版本向量删除、URL 保留）、旧记录保留、历史建议可检索。
- **T14（PASS）**：10 场景全过；核心规则"必要索引未完成→禁止进入 Agent"在无隐式兜底的情况下成立。
- **T21（PARTIAL）**：四模式对比完成（n=8 人工标注，仅作相对比较）：
  - 基线 A：Recall@5=0.688，MRR=0.715，均延 ~285ms
  - 改写 B（qwen-flash LIVE）：指标持平，延迟 +700ms；**观察到改写幻觉偏离**（把问题改写成含 "DeepSeek-V2/V3/Max" 等未证实版本名），改写必须加"不编造"约束与校验
  - 重排 C/D：BM25 代理重排下 MRR 0.688→0.75（D），样本太小不足为凭
  - 失败模式：改写/Rerank 不可用时退化基础检索路径已验证（T16）
  - 推荐触发条件：基础检索 top5 无相关/候选不足，或查询含版本/跨时间语义时再启用改写；Rerank 待真实服务确认后启用
- **T22（PASS）**：9 场景全过；缓存键=文本hash+模型+切分/预处理版本；实测节省调用（3 命中/6 计算）；08:00 清理不波及。

## 是否可以继续

可以。Qdrant 方案整体成立。两个实施注意：① 生产用 Qdrant 1.20 原生 sparse/BM25（替代本轮客户端 BM25 代理）；② Rerank 需要确认 DashScope 可用模型（gte-rerank 调用未成功）或换本地轻量重排。

## 对开发的影响

- 晨报 SQLite 与 Qdrant 的索引状态字段（qdrant_indexed + 版本）是阻塞门的基础，已验证。
- Embedding 缓存直接放晨报 SQLite 即可，无需 Redis。
