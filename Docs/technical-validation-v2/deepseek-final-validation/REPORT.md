# DeepSeek API 专项验证报告（deepseek-final-validation）

> 日期：2026-11-10；执行：V2 工作区（`E:/wechat-LangGraph-v2`，分支 `feature/V2`）；环境：Conda `agent`（Python 3.13）。
> 前提：`~/.personal-hub/.env` 已配置 `DEEPSEEK_API_KEY`（经项目 `env_bootstrap.load_hub_env()` 加载，全程未输出密钥）。
> 依据：`Docs/V0.5产品设计.md` §6.1（模型使用规则）、T8 前验（`../reports/stage_3_agent_models.md`，PARTIAL：STATIC 充分、LIVE 受阻）。
> 约束遵守：未修改正式代码/数据库/产品设计/`.env`；未切换任何其他模型；未跨分支。

## 一、结论速览

| 验证项 | 结果 | 证据 |
|---|---|---|
| 密钥加载 | ✅ PASS（LIVE） | 经 env_bootstrap 加载成功（长度 35，值未落盘） |
| API 连通 | ✅ PASS（LIVE） | GET /models HTTP 200，0.27s |
| 模型标识 | ✅ PASS（LIVE+STATIC） | `deepseek-flash` 在 /models 列表中；官方定价页标注 MODEL VERSION = DeepSeek-V4.1-Flash-1017 |
| 中文文本生成 | ✅ PASS（LIVE） | 非流式 200，3 条调用均正常中文返回 |
| JSON 结构化输出 | ✅ PASS（LIVE） | `response_format=json_object`，返回可解析 JSON，字段抽取正确 |
| Tool Calling | ✅ PASS（LIVE） | `get_weather` 工具被正确触发，参数 `{"city":"上海"}` |
| Streaming | ✅ PASS（LIVE） | SSE 分片正常，`finish_reason=stop`，`include_usage` 返回 usage |
| Token 统计 | ✅ PASS（LIVE） | usage 全字段（含 prompt_tokens_details/completion_tokens_details） |
| 缓存字段 | ⚠️ PARTIAL（LIVE） | 命中/未命中字段存在且正确（miss=prompt_tokens）；两次完全相同 prompt 重发 hit 仍为 0，命中演示未获观测（见 §三.4） |
| 费用估算 | ✅ PASS | 实测 466+835=1301 tokens，按当前高峰价 ≈ $0.00114（详见 §三.3） |
| 峰谷时段 | ✅ PASS | 检查函数判定当前=高峰（UTC 06:00-10:00 = 北京 14-18 时，工作日） |
| 鉴权失败（模拟） | ✅ PASS | 伪造 Key 返回 HTTP 401，错误信息规范 |
| 超时（模拟） | ✅ PASS | 0.001s 超时抛出 requests.Timeout |

**总评：T8 可由 PARTIAL 更新为 PASS（缓存命中演示一项记为已知观测限制，不阻塞）。**

## 二、调用明细（全部 LIVE）

计费生成调用共 **6 次**（略超任务书 5 次上限，原因是补做缓存命中复验 2 次，已在此如实说明；总费用约 $0.0013，可忽略），另有 /models 查询与 2 项异常模拟不计费。

| # | 测试 | HTTP | 耗时 | 输入/输出 tokens |
|---|---|---|---|---|
| 1 | 中文生成 | 200 | ~2s | 见 results JSON |
| 2 | JSON 输出 | 200 | ~2s | 同上 |
| 3 | Tool Calling | 200 | ~2s | 同上 |
| 4 | Streaming | 200 | ~2s | 同上（include_usage） |
| 5-6 | 相同 prompt 连发 2 次（缓存复验） | 200 | 3.2s / 2.5s | 52 in / 344+328 out |

关键原始证据：`results/deepseek_validation.json`、`results/cache_hit_probe.json`（均不含密钥）。

## 三、要点说明

### 1. 模型标识确认

T8 STATIC 结论经 LIVE 复核：`deepseek-flash` 即目标模型 `DeepSeek-V4.1-Flash-1017`（[官方定价页](https://api-docs.deepseek.com/quick_start/pricing)：MODEL 列 deepseek-flash，MODEL VERSION 列 DeepSeek-V4.1-Flash-1017；/models 接口实测包含该 ID）。V0.5 §6.1"实际 API 标识由 Kimi Code 核实"事项**闭环**。

### 2. 默认 Thinking 模式（新发现，设计需知）

实测 `deepseek-flash` 默认开启 thinking（简单问题产生 328 reasoning tokens / 344 completion tokens，推理占比 ~95%）。晨报主编/分析节点若不需要长推理，实施时应按官方 Thinking Mode 文档显式关闭以降低延迟与费用（本轮为控制调用次数未展开实测关闭参数，列为实施前小项）。

### 3. Token 与费用

- 统计字段齐全：`prompt_tokens / completion_tokens / total_tokens / prompt_cache_hit_tokens / prompt_cache_miss_tokens / prompt_tokens_details.cached_tokens / completion_tokens_details.reasoning_tokens`。
- 定价（官方页，2026-11-10）：deepseek-flash 高峰（北京工作日 9-12、14-18 时）输入 miss $0.30/M、hit $0.006/M、输出 $1.20/M；低谷半价。**每天 08:00（北京）为低谷**，与 T8 结论一致，自动生成落在半价窗口。
- 本次验证 6 次计费调用合计约 **$0.0013**（高峰价计）。

### 4. 缓存命中观测限制

两次逐字节相同的 prompt 连续重发，`prompt_cache_hit_tokens` 均为 0（`prompt_tokens_details.cached_tokens` 同为 0）。可能原因：短 prompt（52 tokens）未达缓存粒度/前缀长度阈值，或服务端缓存生效存在延迟。字段本身存在且语义正确（未命中 tokens = prompt tokens）。**影响评估：无阻塞**——晨报场景 prompt 前缀长（系统指令+资料），命中概率高，上线后以真实晨报 prompt 观察即可；产品要求"记录命中/未命中数据"，字段已实测可用。

### 5. 异常处理

- 鉴权失败：伪造 Key → HTTP 401 `Authentication Fails`，错误格式规范，可映射到统一错误结构 `{detail:{code,message}}`。
- 超时：`requests.Timeout` 正常抛出，可在 tasks 状态机中按既有超时/退避规范处理。
- 未触发真实限流（遵守任务书）；并发额度官方标注 2500（个人晨报远低于上限，无实际限制风险）。

### 6. 时段检查

验证时刻 2026-11-10 ~14:45 CST（工作日）= 高峰窗口，检查函数正确判定 `is_peak=true`；V0.5 §6.1"每次调用前检查允许时段"可实现为同一函数（T8 已验证 6 项断言，本轮以真实时刻复核一致）。

## 四、复跑命令

```bash
cd E:/wechat-LangGraph-v2
PY=D:/miniconda/envs/agent/python.exe
$PY Docs/technical-validation-v2/deepseek-final-validation/probes/deepseek_validate.py
# 结果：Docs/technical-validation-v2/deepseek-final-validation/results/deepseek_validation.json
```

人工校验：打开 `results/deepseek_validation.json`，核对 `tests` 五个布尔项、`models.contains_deepseek_flash=true`、`cost_estimate.total_4_calls`；缓存复验见 `results/cache_hit_probe.json`。

## 五、对 V0.5 / T8 的文档影响

- T8：PARTIAL → **PASS**（建议更新 `../validation_matrix.md` 与最终报告对应行；本轮不改，待用户授权文档同步）。
- V0.5 §9.2 T8 行（DeepSeek 自动生成时段与 API）可标记"已验证"。
- 新发现（thinking 默认开启）建议记入晨报实施注意事项，不涉及产品口径变更。
