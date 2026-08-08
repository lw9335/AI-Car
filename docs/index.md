# RoadMind 文档中心

这套文档同时服务两种目标：第一，任何开发者都能运行、验证和扩展项目；第二，项目作者能够用自己的语言解释每一条简历描述，并应对从业务到代码、从正常流程到异常流程的连续追问。

文档按 Diátaxis 分为四类，面试资料是第五个面向项目作者的专题区。

## 学习路径

### 第 1 天：先把项目跑起来

1. 阅读 [本地完整业务闭环](tutorials/本地完整业务闭环.md)，亲手走完创建、初诊、专家确认、调度/配件 Join、开工和结案。
2. 用同一教程模拟现场改诊，观察旧计划冻结、资源释放和 `plan_version` 递增。
3. 完成 [一致性与故障注入实验](tutorials/一致性与故障注入实验.md)，亲手验证陈旧写、幂等重试、熔断和结案驳回。
3. 打开 `/docs`，对照浏览器 Network 面板认识 API。

### 第 2 天：理解核心设计

1. [总体架构与七层映射](explanation/总体架构与七层映射.md)
2. [Agent 编排、HITL 与一致性](explanation/Agent编排HITL与一致性.md)
3. [Hybrid RAG 与证据链](explanation/Hybrid-RAG与证据链.md)
4. [调度、配件与运营三个领域](explanation/调度配件与运营.md)

### 第 3 天：把代码和术语对上

1. [领域模型与状态机](reference/领域模型与状态机.md)
2. [API 与 MCP 工具参考](reference/API与MCP工具参考.md)
3. [需求追踪矩阵](需求追踪矩阵.md)

### 第 4 天以后：面试训练

1. [项目全量学习手册](interview/项目全量学习手册.md)
2. [简历逐词追问映射](interview/简历逐词追问映射.md)
3. [高频深挖题库](interview/高频深挖题库.md)
4. [STAR、白板与不同时间版本](interview/STAR与白板讲解.md)
5. [真实性边界与回答口径](interview/真实性边界与回答口径.md)

## 术语约定

- **工单 / 服务请求**：代码中的 `WorkOrder`，主键是 `service_request_id`。
- **L0**：跨领域共享、可审计的业务真源；当前由 Repository 端口持久化。
- **领域草稿**：诊断候选、调度候选等尚未确认的结构化输出，不能覆盖 L0 已确认事实。
- **初诊**：Agent 依据 DTC、遥测和证据产生的候选结论。
- **确诊**：专家或现场专检确认后的 `confirmed_code`。
- **Parent**：负责意图、缺失信息、粗路由和动态 Task Plan 的总控 Agent。
- **Workflow**：高风险、重复、需要恢复或补偿的显式 LangGraph。
- **HITL**：Human-in-the-loop，人在环审批。
- **REPLAN**：冻结旧计划、执行补偿、递增版本后重新规划。
- **MCP Gateway**：Agent 调用业务系统的统一策略执行点，不把工具描述当成授权。
- **Evidence Ref**：可回到手册/案例具体版本与章节的证据引用。
