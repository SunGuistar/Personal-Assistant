# Qdrant 开发环境预检报告（qdrant-dev-precheck）

> 日期：2026-11-10；执行：V2 工作区（`E:/wechat-LangGraph-v2`，分支 `feature/V2`）。
> 依据：V0.6 产品设计 §4.3/§5.2（Qdrant 两类历史资料 Dense+BM25 混合检索：技术资讯 Collection + 历史晨报 Collection）、V0.6.1 §3.1/§8.3、T12/T13/T14 前验报告。
> 文档说明：本预检执行期间 `Docs/V0.6产品设计.md`、`Docs/V0.6.1额外信息.md` 由用户放入工作区（未提交）；预检结论已对照 V0.6 复核一致。
> 约束遵守：未修改 main 工作区、正式代码、产品设计、SQLite/Chroma；仅创建并清理了临时测试 Collection；未开展晨报功能开发。

## 结论速览：全部 PASS，已满足 V2.0 正式开发前置条件

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 1 | Qdrant 安装与运行 | ✅ PASS（LIVE） | 镜像 qdrant/qdrant:v1.20.0 已存在；新容器 `personal-hub-qdrant` 运行中，`/healthz` 通过 |
| 2 | agent 环境连接 | ✅ PASS（LIVE） | qdrant-client 1.20.0 已装入 Conda `agent`（原缺失，本轮安装）；`QdrantClient` 连接、建删 Collection 正常 |
| 3 | 向量写入/查询/更新/删除 | ✅ PASS（LIVE） | 4 点写入→稠密 top2 正确→payload 与向量覆写生效→删除后 count=3（`results/qdrant_precheck.json` phase1） |
| 4 | Dense + Sparse/BM25 混合检索 | ✅ PASS（LIVE） | named vectors（dense cosine + sparse IDF）；稀疏检索 top1 命中预期点；RRF Fusion 混合检索正常；重启后仍正常 |
| 5 | 持久化与重启恢复 | ✅ PASS（LIVE） | `docker restart` 后 Collection、count=3、更新 payload、混合检索结果全部保留（phase2） |
| 6 | 临时数据清理 | ✅ PASS | 测试 Collection 已删除，`remaining_collections: []`；未触碰任何其他数据（本容器本就没有其他 Collection） |

## 环境现状（检查前 → 检查后）

- 检查前：Docker Desktop（D:\Docker，引擎 28.3.3）**已安装但未运行**；无 Qdrant 容器/卷（T12 的测试容器当时已按规范删除）；agent 环境**未安装** qdrant-client；6333/6334 端口空闲。
- 执行动作（均为新增、可逆、无管理员权限）：
  1. 启动 Docker Desktop（用户空间应用，非系统服务修改）；
  2. 创建容器 `personal-hub-qdrant`：`-p 6333:6333 -p 6334:6334 -v qdrant_dev_storage:/qdrant/storage --restart unless-stopped`（命名卷持久化，与 T12 验证过的部署方式一致）；
  3. Conda `agent` 环境 `pip install qdrant-client`（1.20.0，纯 Python 包，与镜像版本一致）。
- 检查后：容器常驻运行，环境可开发。

## 重要发现：客户端必须用 `127.0.0.1`，不能用 `localhost`

实测（LIVE）：`QdrantClient(url="http://localhost:6333")` **每次请求固定阻塞约 21 秒**；`http://127.0.0.1:6333` 为 10ms 级。根因：Windows 上 `localhost` 优先解析到 IPv6 `::1`，而 Docker Desktop 的 Windows 侧 IPv6 转发不通，连接挂起直至回退 IPv4。curl 不受影响（其解析顺序不同）。

**开发规范建议**：项目 Qdrant 客户端统一配置 `http://127.0.0.1:6333`（或配置项默认 127.0.0.1）；开发文档中显式写明，避免每次请求 21 秒劣化（本预检脚本初版即踩中，已修复并留档）。

## 与现有项目兼容性

- 代码库现状：`app/` 与 `app/config.py`、`.env.example` 中**无任何 qdrant 引用**——纯新增集成，无版本/端口/配置冲突。
- 两个独立 Collection（AI 技术资讯 / 历史晨报）：完全可行（Qdrant Collection 天然隔离；本轮已验证多 named-vector Collection 的建删与检索）。T13 已验证中文 Dense+BM25 检索命中，本轮复核混合检索链路（prefetch + RRF）可用。
- 端口：6333（REST）/6334（gRPC）独占，无冲突。
- 数据：命名卷 `qdrant_dev_storage` 专供晨报开发；Chroma（微信模块）与 SQLite 完全不受影响。

## 复现命令

```bash
# 环境状态
docker ps --filter name=personal-hub-qdrant
curl -s http://127.0.0.1:6333/healthz          # 注意：用 127.0.0.1，localhost 会卡 21s

# 功能与持久化测试（phase1 → 重启 → phase2，自动清理）
PY=D:/miniconda/envs/agent/python.exe
cd Docs/technical-validation-v2/qdrant-dev-precheck
$PY probes/qdrant_precheck.py phase1
docker restart personal-hub-qdrant && sleep 10
$PY probes/qdrant_precheck.py phase2
# 结果：results/qdrant_precheck.json
```

## 遗留与建议（不阻塞开发）

1. `localhost` vs `127.0.0.1` 问题写入开发规范（见上）。
2. 备份方案沿用 T12 结论：file:// recover 在 1.20 返回 404，可用路径是 download + multipart upload。
3. Docker Desktop 需随开机自启（现为手动启动；容器设了 `--restart unless-stopped`，但引擎本身不启动则容器不会运行）。如需设置 Docker Desktop 开机自启，涉及用户级设置，由用户决定。
4. 生产备份策略（V2.0 需求）在正式开发排期中保留（D1：第一版无备份，以隔离规范替代——不影响开发启动）。
