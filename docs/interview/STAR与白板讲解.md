# STAR、白板与不同时间版本

## 30 秒版本

> 我做的是 AI 商用车售后维修知识与服务协同平台。核心不是聊天，而是用一张 L0 工单把维修、调度、配件和运营四个 Agent 串起来。Parent 负责动态理解，审批、并行履约和改诊补偿用 LangGraph 固化；诊断用带品牌车型过滤和证据引用的 Hybrid RAG，调度用 CP-SAT，所有业务工具经 MCP Gateway。样板有完整 Web/API 和 27 项测试，外部系统通过适配器生产化。

## 90 秒版本

> 背景是商用车售后信息散在电话、DMS、专检、库存和工程师之间，实际停工时间常耗在协同。我的方案把每次服务请求作为 L0 聚合，thread_id 就是工单 ID，所有领域 Agent 只返回结构化草稿。维修 Agent 先按燃油/新能源硬路由，再做 BM25、向量、结构过滤和故障图融合，输出带版本 evidence_refs 的初诊包，专家确认后才能进入配件。调度先硬过滤，再用 OR-Tools CP-SAT 综合技能、ETA 和负载，最终由调度员审批；配件支持 VIN 兼容和原厂/副厂 BRING_BOTH。两支线都准备好才允许开工。现场改诊会冻结旧计划、释放人员和库存、plan_version 加一再诊断。外部调用统一经 MCP Gateway 做 scope、限流、熔断、审计，Trace 按工单贯穿。仓库默认是无密钥可运行样板，核心不变量已有测试，PostgreSQL、Redis、Kafka、真实 OEM/WMS 是明确的生产替换点。

## 5 分钟白板顺序

### 第 1 分钟：画业务闭环

```text
故障上报 -> 总控 -> 初诊 -> 专家 -> [调度 || 配件] -> 现场 -> 结案 -> 知识/运营
```

强调两个门：初诊/确诊；候选/履约。

### 第 2 分钟：画控制面

上层 Parent，中央 LangGraph，底层 Domain/StateMachine，右侧 MCP Gateway，中心 L0 WorkOrder。

说：LLM 做开放决策，Workflow 控流程，Domain 守不变量，Gateway 管副作用。

### 第 3 分钟：画诊断 RAG

```text
品牌车型过滤 -> BM25 / Vector / Graph -> RRF -> Rerank -> EvidenceRef -> Expert
```

强调硬过滤在召回前，证据有版本章节。

### 第 4 分钟：画履约 Join

调度：硬过滤 -> CP-SAT -> 人工 -> lease。配件：确诊 -> VIN/BOM -> ATP -> reserve。AND Join 后 READY。

### 第 5 分钟：画异常

Mismatch -> freeze V1 -> compensate -> V2 -> rediagnose。补充 Outbox、Trace 和人工接管。

## STAR 故事一：初诊和确诊分离

**S**：AI 能生成维修建议，但如果直接驱动配件和派工，错误成本和安全风险高。

**T**：既利用模型提高信息整理效率，又不让模型越过责任边界。

**A**：定义 DiagnosisPackage 与 evidence_refs；requires_expert 固定为 true；专家按 diagnosis_id 确认；PartsAgent 以 confirmed_code 为硬门禁；新能源增加 HV 规则。

**R**：形成可测试不变量：无确认不能配件履约、旧诊断不能迟到确认、无 DTC 不猜件号。这里不要编造业务百分比，可说“自动化测试直接覆盖”。

## STAR 故事二：现场改诊的一致性

**S**：远程初诊和现场专检可能不一致，若只更新诊断文本，旧件和旧人员仍继续履约。

**T**：让跨系统流程在部分成功后仍可恢复。

**A**：设计 plan_version、frozen_versions 和 REDIAGNOSIS_REQUIRED；LangGraph 固化 freeze/compensate/increment；释放 lease 和库存，清空 confirmed_code；Outbox/事件留痕；超过阈值人工接管。

**R**：测试证明库存恢复、旧资源清空、版本递增和补偿事件完整。生产物流补偿作为同一 Saga 的外部适配点。

## STAR 故事三：调度可解释和可约束

**S**：让 LLM 直接选人容易漏高压资质、排班或品牌约束。

**T**：兼顾约束满足、目标优化和人工最终决策。

**A**：先按品牌/模式/动力/HV 硬过滤；用 CP-SAT 最大化技能、ETA、负载目标；独立验证器复核；审批 token 后建立短租约。

**R**：EV 测试断言所有候选均有 hv_certified，最优候选排第一，无效 token 被拒绝。

## STAR 故事四：运营问数安全

**S**：自然语言生成自由 SQL 会带来越权、口径和成本风险。

**T**：保留自然语言体验，同时限制数据平面。

**A**：指标语义层映射 metric_id；模板查询；RBAC/ABAC；输出拆 fact/inference/recommendation/scenario。

**R**：自由 SQL 测试被拒，What-if 明确标记非事实。

## 被追问“不熟的库”时

先回答不变量，再回答当前实现，最后回答生产替换。例如：

> 我对 Redis 在这里的核心要求不是“用了 Redis”四个字，而是 NX+TTL 的租约语义、续租/释放的 compare-and-set 和业务真源分离。样板用 LeaseBook 验证并发占用契约，生产实现会换成 Lua 原子操作。

这比堆命令更能证明理解。

## 反问面试官

- 你们的 Agent 写操作是否有统一审批和幂等边界？
- RAG 的车型/租户隔离是在召回前还是生成后处理？
- 线上评测更关注模型指标还是业务不变量？
- 生产 Trace 如何脱敏并进入回归 Dataset？
- Workflow checkpoint 与业务数据库的版本如何对齐？
