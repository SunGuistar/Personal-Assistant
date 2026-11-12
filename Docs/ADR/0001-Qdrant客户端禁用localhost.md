# ADR-0001：Qdrant 客户端必须使用 127.0.0.1，禁止 localhost

- 日期：2026-11-10（开发预检实测）；2026-11-12 归档为 ADR。
- 状态：已采纳，已写入 `AGENTS.md` §10 硬约束。
- 前身：`Docs/technical-validation-v2/qdrant-dev-precheck/REPORT.md`（Qdrant 开发环境预检报告，全文见 Git 历史）。

## 背景

晨报模块使用 Qdrant（Docker 容器 `personal-hub-qdrant`，端口 6333/6334）存储技术资讯与历史晨报向量（Dense + BM25 混合检索）。开发预检（LIVE）中实测发现：客户端地址写法在 Windows 上直接决定可用性。

## 实测证据（LIVE，2026-11-10）

- `QdrantClient(url="http://localhost:6333")`：**每次请求固定阻塞约 21 秒**。
- `QdrantClient(url="http://127.0.0.1:6333")`：10ms 级，正常。
- 根因：Windows 上 `localhost` 优先解析到 IPv6 `::1`，而 Docker Desktop 的 Windows 侧 IPv6 转发不通，连接挂起直至回退 IPv4。curl 因解析顺序不同不受影响。
- 预检脚本初版即踩中此问题，修复后留档。

## 决策

项目内所有 Qdrant 客户端统一使用 `http://127.0.0.1:6333`（或配置项默认 127.0.0.1），**禁止使用 localhost**。

## 影响

- 约束 `app/morning_report/` 全部 Qdrant 访问及测试（含 `tmp_mr_*` 前缀测试 Collection）。
- 相关环境结论：容器 `personal-hub-qdrant` 使用命名卷 `qdrant_dev_storage` 持久化、`--restart unless-stopped`；Docker Desktop 引擎本身需运行（开机自启为用户级设置，由用户决定）。
