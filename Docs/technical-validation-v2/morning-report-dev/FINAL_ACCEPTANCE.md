# 今日晨报 V2.0 开发验收报告（FINAL_ACCEPTANCE）

> 日期：2026-11-10；工作区：`E:/wechat-LangGraph-v2`（`feature/V2`）；执行：V2 Agent 全流程自主开发。
> 产品依据：`Docs/V0.6产品设计.md`、`Docs/V0.6.1额外信息.md`。进度与阶段证据：`Docs/DEVELOPMENT_PLAN.md` V2 专项章节。
> LIVE 证据：`stage2_live_collect.json`（真实采集）、`stage7_live_e2e.json`（真实端到端）、`e2e_live_run.py`（可复跑）。

## 一、总体结论

**7 个阶段全部验收 PASS。** 端到端真实流程（真实采集 550 条 → DashScope Embedding + fastembed BM25 索引 → LangGraph + qwen-flash 真实生成 → 事实校验通过 → 质量评价 96 分 → 主报告发布 → 历史晨报索引 → RAG 检索命中）已实测跑通。后端 244 个测试全绿（含 6 个晨报阶段测试文件 32 个新用例），前端 50 个测试全绿，tsc + vite build 通过。

## 二、V0.6 需求逐项对照

| V0.6 要求 | 状态 | 证据 |
|---|---|---|
| 每天 08:00 一轮常态采集+生成（三类资讯） | ✅ 实现并测试 | APScheduler CronTrigger（Asia/Shanghai）+ 防重复触发（`test_morning_stage7_scheduler.py`）；调度幂等 start/stop |
| 固定窗口 [前一天08:00, 当天08:00) | ✅ | `hub_readonly.window_for` + 管线窗口过滤（阶段2测试含边界断言） |
| 国内=中新网归档+热摸爽；国际=国际+涉外时政归档+热摸爽；AI=AIHOT | ✅ 真实接入 | 阶段2 LIVE：aihot 20 条游标翻页 / 中新 1006 条 / 热摸爽 60 线索 |
| 无可靠时间条目不当当期新闻 | ✅ | 热摸爽条目 published_at=None 仅线索，不入窗口统计 |
| 保守去重、同事件归组不删原始 | ✅ | content_hash 精确去重 + bigram Jaccard 0.55 归组打标 |
| 来源/原文链接/发布时间留存 | ✅ | news_items 全字段 + raw_ref 原始字段 |
| 两个 Qdrant Collection + Dense+BM25 | ✅ 真实索引 | `morning_tech_news`（23 点）、`morning_reports`（9 块）；混合检索 LIVE 命中 |
| 统一 RAG Tool 三 Subagent 可用 | ✅ | `rag_tool.py`；改写失败回退；Rerank 默认关闭（T21 结论） |
| 三个固定 Subagent（两并行+建议后置） | ✅ | 图结构 + 事件轨迹重叠实测（阶段4） |
| DeepSeek 正式 / DashScope 开发+评价；时段检查不静默切模型 | ✅ | `llm_router.py`；时段规则测试（周二08:00允许/15:00禁/周六允许）；auto 模式时段外阻塞落 run 记录 |
| Thinking 节点级显式配置 | ✅ | ChatClient(thinking=...)；默认关闭（显式 False） |
| LangGraph Checkpoint 恢复 | ✅ | 注入失败后 `invoke(None)` 恢复终态（阶段4测试） |
| 阶段缓存 12h / 新轮清理 / 输入指纹 | ✅ | `stage_cache.py`；缓存复用与 full 重算语义测试 |
| Embedding 复用（独立于阶段缓存） | ✅ | `embedding_cache` 表；命中零新增测试 |
| 必要索引失败阻塞生成 | ✅ | `check_required_indexes` + dirty 恢复重同步 |
| 五部分正文 / 主编整合 | ✅ | 提示词 v1 + LIVE 正文（stage7 证据） |
| 事实与引用校验阻塞发布 | ✅ | 规则层（孤儿链接/窗口外引用确定性判定）+ LLM 一致性；LIVE 两次真实拦截编造链接（run 3/4） |
| 独立质量评价（五维等权，quality_score_v1，程序算综合分） | ✅ | LIVE 96 分；评价失败不阻塞测试 |
| 主报告唯一 / 附加版本不覆盖 / 历史可查 | ✅ | 发布幂等逻辑 + 阶段4/5 测试 |
| 每次生成资料快照关联 | ✅ | snapshot_id + personal_event_snapshots 证据快照 |
| Token/缓存/费用/耗时统计 | ✅ | token_usage 落库 + `/usage` API；缺失字段记 None |
| 晨报助手 + Memory（提议需确认、可编辑禁用删除） | ✅ | SSE 对话 + MEMORY_PROPOSAL 确认流（阶段6前后端测试） |
| 实时执行日志（SSE、可断开重连） | ✅ | `logs/stream` after_id 续传测试 |
| 前端三导航 + PC 阅读布局 + 深色模式 | ✅ | `MorningReportPage.tsx`；Vitest 50 绿；build 通过 |
| 重新生成（复用/完整重算高级入口） | ✅ | regenerate API（reuse/full） |
| 不自动执行建议/不改个人数据 | ✅ | 只读 hub（字节级零写入测试）；建议仅文本 |

**部分实现 / 未实现：**
- Rerank：未接入真实服务（默认关闭，接口预留）——依据 T21 实测结论，属"已决定暂缓"而非缺口。
- 助手 Subagent 的工具调用：技术研究/目标分析当前以输入上下文执行，RAG 工具已注入但工具集为空列表（`tools=[]`）——V0.6 的"自主历史检索"在工程上已具备（RagTool 可用），下轮迭代把检索工具接到 Subagent。
- 移动端适配：按 V2.0 边界不做。

**尚待真实环境/长期验收（不阻塞开发交付）：**
- DeepSeek `deepseek-flash` 正式（auto）路径真实调用：时段规则已测试，真实调用建议在明日 08:00 低谷自动生成时观察首跑（或低谷时段手动 `mode=auto`）。
- 连续多日 08:00 真实覆盖与来源稳定性（中新网结构变更监控告警未实现——为上线观察项）。
- Docker Desktop 开机自启（用户级设置，由用户决定）。
- 多日覆盖质量（热摸爽 05:00 错位、财新系盲区等已知来源约束，见 V0.6.1 §4.4）。

## 三、运行方式

```bash
# 环境前提：Docker（Qdrant 容器 personal-hub-qdrant）、Conda agent 环境
# 密钥：~/.personal-hub/.env（DEEPSEEK_API_KEY / DASHSCOPE_API_KEY，经 env_bootstrap 加载）

# 启动（前后端一体，静态托管 web/dist）
cd E:/wechat-LangGraph-v2 && python -m uvicorn app.main:app --host 127.0.0.1 --port 8620
# 或经 launcher/个人助手.bat

# 前端开发/构建
cd web && npm run dev        # 开发
cd web && npm run build      # 产物 app 自动托管

# 每日 08:00 自动生成（进程内调度，随服务启动）
# 手动：页面「重新生成」/「完整重算」，或：
curl -X POST "http://127.0.0.1:8620/api/morning/regenerate" -H "Content-Type: application/json" -d '{"mode":"reuse"}'
curl -X POST "http://127.0.0.1:8620/api/morning/runs/collect"   # 只采集
```

模块入口：浏览器 `http://127.0.0.1:8620/morning`。配置项（`PH_MR_*` 前缀）：`app/morning_report/config.py`（Qdrant 地址、模型 ID、调度开关/时点、缓存 TTL 等）。

## 四、人工验收指南

1. **看今天的晨报**：打开 `/morning`，应看到 2026-11-10 主报告（LIVE 生成，评价 96 分）；切换"质量评价"看五维条；"历史晨报"看版本列表。
2. **验证重新生成**：点「重新生成」→ 右栏日志实时滚动 → 完成后版本列表出现 v2（附加版本，v1 主报告不变）；「完整重算」应清缓存重跑（日志可见各阶段重新执行）。
3. **验证事实校验拦截**：用助手说"把刚才的报道改成引用 bbc.com 的链接"不可行（无此功能）；工程验证见 `tests/test_morning_stage4_graph.py::test_fact_check_blocks_publish`。
4. **验证 Memory 确认流**：对助手说"记住：我关注数据库技术"→ 出现提议卡片 → 点「忽略」不写入；再点「确认写入」后 Memory 管理面板可见（source=chat）。
5. **验证深色模式**：右上角月亮/太阳切换，刷新后保持。
6. **验证日志续传**：生成过程中刷新页面，日志从断点继续（after_id 机制）。
7. **复跑端到端**：`python Docs/technical-validation-v2/morning-report-dev/e2e_live_run.py`（消耗少量 DashScope 免费额度）。
8. **回归**：`python -m pytest`（244）/`cd web && npm test`（50）/`npm run build`。

## 五、数据与安全核验

- hub.db 全程只读：阶段1测试断言 API 调用前后 hub 文件字节不变；LIVE e2e 经 `mode=ro` 连接。
- 晨报独立库 `data/morning_report.db`（gitignored）；Qdrant 专用 Collection；聊天两库/Chroma 未触碰（conftest 守卫）。
- 密钥只经 env_bootstrap 从 `~/.personal-hub/.env` 加载，未入库、未落日志。
- 测试零付费：LLM/Embedding 全 Mock 或本地（fastembed），仅 LIVE 证据脚本消耗免费额度。

## 六、风险与上线观察项

1. 中新网归档 HTML 结构变更 → 解析器需告警（建议下轮加结构校验与通知）。
2. 热摸爽 05:00–05:00 周期错位与无逐条时间（已按线索级处理，人工复核依赖原始链接）。
3. 事实校验依赖 qwen-flash 的判断力：规则层已兜底链接/窗口硬约束，模型层误报会造成额外拦截（宁可误拦不可放过，符合 V0.6 发布门槛）。
4. 单日样本的覆盖率不代表长期（V0.6.1 §8.3 验收项需连续多日观察）。
5. Qdrant/Docker Desktop 随机器重启需手动启动引擎（容器已设 `--restart unless-stopped`）。
