# T1–T22 验证矩阵（2026-11-08 轮）

状态：PASS / PARTIAL / FAIL / BLOCKED / NOT_TESTED；证据类型：LIVE / INTEGRATION / SIMULATION / STATIC。
统计（最终）：PASS 12、PARTIAL 7、BLOCKED 3、FAIL 0、NOT_TESTED 0（合计 22）。
证据根目录：`Docs/technical-validation-v2/results/`（JSON）、`probes/`（可复跑脚本）、`fixtures/`。

| 编号 | 验证目标 | 状态 | 证据类型 | 实测结果摘要 | 证据路径 | 阻塞开发 | 解决建议 |
|---|---|---|---|---|---|---|---|
| T1 | 原库“我的昨日”历史数据可用性 | **PARTIAL** | STATIC+LIVE | daily_tasks 完成事件可还原（34 完成中 31 有 completed_at，12 条完成时间≠任务日；测试窗口 8 条完成事件可查）；GitHub 1097 commits 全历史；长期计划/标红可查；memos/important_infos/books 只有 created/updated，无完成语义；completed_at 单值覆盖，取消再完成会丢历史 | results/t1_hub_schema.json | 否 | 晨报模块自建只读事件快照表（不动原库）；完成/取消完成事件从上线起记录 |
| T2 | 国内社会资讯源 | **PARTIAL** | LIVE | GDELT v2 可用（中文源 48h 内 20+ 条，含标题/域名/时间，无正文）；中新网 RSS 可用（30 条，标题/链接/时间/短摘要）；新华网/澎湃 RSS 不可用；百度热搜 API 结构变更未取到 | results/t2_cn_sources.json、results/net_round2.json、net_round3.json | 是（弱） | 主源 GDELT+中新网 RSS，重大新闻辅百度热搜（需适配新结构）；正文回溯原站抓取 |
| T3 | 国际社会资讯源（BBC 等） | **BLOCKED** | LIVE(失败)+STATIC | 本机网络无法解析 feeds.bbci.co.uk/CNN/AlJazeera（getaddrinfo failed），无可用代理；github.blog RSS 可达证明部分国际站通 | results/t3_intl_sources.json | 是 | 需代理/网络出口或改用可达国际源；BBC RSS 字段设计（标题/UTC 时间/链接/摘要）已核查文档 |
| T4 | AIHOT 机制 | **BLOCKED** | LIVE(失败)+STATIC | aihot.cn/.com DNS 失败；aihot.cc 证书域名不匹配；无法取得其热度指标定义，不能语义化解释热度 | results/t4_aihot.json | 是（AI 源可替代） | 以 hotai.news（可达、内容确认）+HN+GitHub Blog 替代；AIHOT 待网络可达后再评 |
| T5 | daily.dev 与 hotai.news | **PARTIAL** | LIVE | hotai.news 200 可用（AI 快讯/热议/开源/机会分区）；daily.dev GraphQL 端点可达但公开查询形状失效（introspection 空）；HN API 可用；github.blog RSS 可用 | results/t5_dailydev_hotai.json、net_round2/3.json | 否 | V2.0 接入 hotai.news+HN+GitHub Blog；daily.dev 缓议 |
| T6 | 全文获取与事件聚合 | **PARTIAL** | LIVE+SIMULATION | GitHub Blog 全文提取成功（>300 字）；hotai 首页可提；BBC 不可达（网络）；fixture 聚合：0 误合并，同事件归组保守（阈值 0.25 下 E1/E2/E3 部分未归组=宁留候选）；新进展样本全部保留 | results/t6_fulltext_aggregation.json | 否 | 转载归组阈值需按真实样本再调；正文缺失必须显式标记 |
| T7 | 08:00 最终采集与快照 | **PASS** | SIMULATION | 7 项检查全过：08:00 是启动时刻；迟到但属本期文章纳入；08:00 后发布排除；单源超时（999s 预算 30s）不阻塞；索引失败阻塞 Agent；**快照若不隔离会被后台更新污染（实测）→ 必须快照隔离**；手动重生成用固定窗口 | results/t7_snapshot.json | 否 | 快照采用内容哈希清单+隔离读取 |
| T8 | DeepSeek/DashScope API | **PARTIAL** | STATIC+LIVE | 官方文档确认：DeepSeek-V4.1-Flash-1017 真实存在，API 标识为 `deepseek-flash`（产品写法是版本名不是 API ID）；高峰=工作日 09:00-12:00/14:00-18:00（北京），低谷半价；低谷检查函数 6 断言全过；**DEEPSEEK_API_KEY 未配置→真实调用 BLOCKED**；DashScope：qwen3-vl-plus/qwen-flash 经 OpenAI 兼容端点可用（200），qwen-plus 免费额度耗尽（403），SDK 旧端点对 vl 模型报 400 | results/t8_llm_api.json | 是（自动生成） | ① 配置 DEEPSEEK_API_KEY 后补真实调用验证；② 开发/手动模型用 qwen-flash（免费可用）；③ 用兼容端点而非 dashscope 旧 SDK |
| T9 | 技术资讯与晨报索引 | **PASS** | INTEGRATION | 长文分块（3 块/均 131 字）；全文+来源+URL 入 Qdrant payload；晨报按语义单元带 version_id；更新后旧版本向量删除、URL 保留；旧记录可检索；历史建议可检索且版本可溯 | results/t9_indexing.json | 否 | 生产加 url 字段与分块元数据规范 |
| T10 | 阶段缓存与局部重算 | **PASS** | SIMULATION | 13 场景全过：同输入复用/资讯/个人/Memory/模型/Prompt/改写配置变化局部失效/人工失效/全量重算/重启恢复/12h 过期/08:00 清理保长期/主编与校验必重算；四缓存机制区分记录 | results/t10_stage_cache.json | 否 | — |
| T11 | NewsAPI 专项 | **BLOCKED** | LIVE(失败)+STATIC | newsapi.org 本机连不通（ConnectTimeout）；NEWS_API_KEY 未配置；官方文档：开发者版 100 次/天仅限开发、非商用、正文仅 200 字摘要 | results/t11_newsapi.json | 是（弱，有替代） | 以 GDELT 替代；如购买 key 且网络可达再评估 |
| T12 | Qdrant Windows 部署与持久化 | **PASS** | LIVE | Docker Desktop（D:\Docker）启动后 qdrant/qdrant 1.20.0 容器跑通：CRUD、优雅重启保留、kill -9 后已确认写入不丢、**快照恢复经 download+multipart upload 成功（file:// recover 在 1.20 返回 404）**；端口 8633 无冲突 | results/t12_qdrant_deploy.json | 否 | 备份脚本用 upload 方式；正式部署挂专用 volume |
| T13 | Qdrant 混合检索 | **PASS** | INTEGRATION | 双 Collection（资讯/晨报）建库；dense+BM25（rank_bm25 客户端）+RRF 混合；中文/英文查询命中；发布时间/来源/晨报日期/version_id 过滤均正确；2025 旧晨报可检索不被排除；结果带 title/source 可回溯 | results/t13_hybrid_search.json | 否 | 生产评估 Qdrant 原生 sparse/BM25（1.20 支持）替代客户端 BM25 |
| T14 | SQLite/Qdrant 一致性 | **PASS** | SIMULATION+INTEGRATION | 10 场景全过：正常写入/幂等/中途异常可检测/索引失败→重试修复/正文更新重索引/版本不一致标记/快照冻结/晨报保存但索引失败→**阻塞**/修复后通过 | results/t14_consistency.json | 否 | — |
| T15 | LangGraph 与 LangChain 协作 | **PASS** | SIMULATION | 最小工作流全绿：状态定义/并行节点与状态合并/三 Subagent 固定调用/建议等前两者终态/共享统一 RAG Tool（create_agent 图内并行+串行均触发工具）/AsyncSqliteSaver 检查点/故障注入→恢复→goal 标成功/真并行窗口相交/不用 Deep Agents | results/t15_langgraph_workflow.json | 否 | 生产注意：同 super-step 节点在恢复时会被重跑（LangGraph 语义） |
| T16 | 故障注入与错误兜底 | **PASS** | SIMULATION | 21/21 场景：超时/空结果/正文失败→降级；Qdrant 挂/索引不完整/Embedding 失败→阻塞；改写/Rerank 失败→降基础检索；LLM 超时/限流→重试；拒绝→记录且**不换模型**；建议失败标“分析失败”；主编/严重事实失败→阻塞不发布；评价失败→标未评价；中断恢复不重复主报告；重复触发保护 | results/t16_fault_injection.json | 否 | — |
| T17 | 实时日志与 UI | **PARTIAL** | INTEGRATION+STATIC | 独立 FastAPI+SSE 探针：事件流（节点归属+技术详情）✓、双节点并行事件交错到达 ✓、Last-Event-ID 断线续传 ✓、历史查询 ✓；前端现状核查：React+Tailwind 八页面、无既有 SSE 先例；SSE vs WS 比较完成（推荐 SSE）；**未做正式 UI 原型**（遵守不改正式 UI 约束） | results/t17_sse_ui.json | 否 | 开发期新建晨报页面 + SSE 端点（复用 sse-starlette） |
| T18 | 独立质量评价 | **PASS** | LIVE | qwen-flash 只读正文评价：3 份样本×3 次全部成功结构化输出；综合分 高分 88(波动1)/普通 36(波动0)/低分 20(波动2)，区分度显著；评价失败路径（模型不存在）不阻塞报告；综合分公式对比：等权 vs 0.25/0.25/0.2/0.2/0.1 vs 重逻辑三方案结果接近，推荐等权或轻加权（见报告） | results/t18_quality_eval.json | 否 | 权重方案待产品确认（本报告不作定论） |
| T19 | 六个固定采集时点 | **PASS** | SIMULATION | APScheduler：六时点 next_run_time 全部正确（Asia/Shanghai）；max_instances=1 实测并发=1；任务抛错 scheduler 不崩；SQLite jobstore 重启后任务保留；08:00 采集与 finalize 任务分离不重复采集 | results/t19_scheduler.json | 否 | 项目当前无调度器，新增 APScheduler 依赖即可 |
| T20 | 分层去重与新进展保护 | **PASS** | SIMULATION+LIVE | 10 类 fixture 样本：L1 精确哈希命中同 URL/同内容；L2 simhash+MinHash 无误合并；L3 TF-IDF 事件归组无误合并、同事件保守归组；**真实 DashScope Embedding（14 篇 4 次 API 调用）事件语义归组无误合并对**；新进展/新版本/纠正类样本全部保留 | results/t20_layered_dedup.json、t20_embedding_semantics.json | 否 | 阈值（hamming≤12/jaccard≥0.5/cos≥0.55）为初值，按真实数据调 |
| T21 | Query 改写与 Rerank | **PARTIAL** | INTEGRATION+LIVE | 8 查询×4 模式（A 基线/B 改写/C 重排/D 全启）：改写用 qwen-flash LIVE；Rerank 的 DashScope gte-rerank 调用未通过（模型名/权限）→ BM25 代理重排（已标注）；指标与按需触发建议见阶段二报告；样本量小（n=8）仅作相对比较 | results/t21_rag_modes.json | 否 | 确认 gte-rerank 模型可用名或改用本地重排；按复杂度触发增强 |
| T22 | Embedding 复用缓存 | **PASS** | SIMULATION | 9 场景全过：同文本同模型命中（省 1 次调用）；模型/正文/切分/预处理版本变化正确失效；重启复用；Qdrant payload 复用规则；坏缓存恢复；**08:00 阶段缓存清理不影响 Embedding 缓存** | results/t22_embedding_cache.json | 否 | 缓存表放晨报 SQLite，键=文本hash+模型+切分/预处理版本 |

## 统计

| 状态 | 数量 | 项 |
|---|---|---|
| PASS | 12 | T7、T9、T10、T12、T13、T14、T15、T16、T18、T19、T20、T22 |
| PARTIAL | 7 | T1、T2、T5、T6、T8、T17、T21 |
| FAIL | 0 | — |
| BLOCKED | 3 | T3、T4、T11 |
| NOT_TESTED | 0 | — |
| **合计** | **22** | |
