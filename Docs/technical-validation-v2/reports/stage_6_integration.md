# 阶段六报告：跨组件集成与端到端模拟

## 运行方式

`probes/e2e_integration.py`（正常路径）与 `python probes/e2e_integration.py --block-index`（关键故障路径）。两次运行证据：`results/e2e_integration.json`（正常）与故障路径输出（verdict=索引未完成，工作流未进入 Agent；注：第二次运行覆盖同名结果文件，故障路径结论同时记录于最终报告与事件日志）。

## Mock 与真实组件（显式标注）

- **真实**：晨报独立 SQLite（隔离临时库）、Qdrant 容器（tv2_e2e_news / tv2_e2e_reports）、DashScope Embedding（LIVE）、APScheduler 无关（采集时点为数据模拟）。
- **Mock（SIMULATION）**：六个采集时点的新闻数据、LLM 生成（确定性伪 LLM）、质量评价模型、事实校验结果。**未声称完成真实生产级端到端验证**。

## 正常路径验证结果（全部通过）

1. 08:00 最终采集：窗口 5 条纳入、08:00 后发布的 1 条排除。
2. 分层去重/事件归组：5 篇 → 4 事件，转载归组 1 组。
3. SQLite/Qdrant 写入 + Embedding 增量 + **必要索引门**：gate_open=true。
4. 快照冻结（内容哈希清单）。
5. 普通 LLM 节点并行（asyncio.gather，wall 0.6s 级）。
6. 技术研究/目标分析**真并行**（时间窗口相交），**统一 RAG Tool 均被三个 Subagent 调用**（建议 Subagent 后置）。
7. 主编 → 事实/引用校验 → 独立质量评价（模拟）按序执行。
8. 版本规则：首次手动成功 → 唯一主报告（primary_count=1）；重新生成 → 附加版本不覆盖（primary_body_preserved=true）；评价失败的版本保留（failed_eval_report_kept=true）；历史晨报语义单元 2 条入 Qdrant 且 version_id 可溯。
9. 缓存生命周期：08:00 阶段缓存清理后 Memory 保留。

## 关键故障路径（--block-index）

索引阶段注入失败 → `index_gate.index_ok=false` → **工作流在进入 Agent 前终止**（事件日志止于"必要索引校验：阻塞"），无隐式兜底、无不完整报告。

## 结论

关键组件能按产品既定顺序协作；并行、共享 RAG Tool、索引阻塞门、版本规则、缓存生命周期均通过。剩余差距全是 Mock 部分（真实 LLM 生成质量、真实新闻源、真实调度驱动），属开发期事项。

## 对开发的影响

- 事件日志结构（stage + detail + 时间戳）可直接作为实时日志的数据模型。
- E2E 脚本可作为晨报模块的首个集成测试骨架（替换 Mock 为真实组件）。
