# RoadMind OpenWiki 生成要求

请以简体中文生成和维护本仓库的代码知识库，代码标识符保持原文。

## 目标读者

1. 接手该项目的 Python/Agent 工程师。
2. 需要详细讲解本项目、准备 AI 应用开发面试的项目作者。

## 必须优先覆盖

- 从 `ServiceRequestCreate` 到 `WorkOrder` 结案的完整调用路径。
- L0 工单、thread_id、version、plan_version、Task Plan 与四层记忆边界。
- Parent Agent 与显式 LangGraph Workflow 的职责分离。
- LangGraph parallel fulfillment、mismatch replan、checkpoint/interrupt/resume。
- Hybrid Retriever 的结构过滤、词法、向量、故障图、RRF 和 rerank。
- 初诊/确诊门禁、EvidenceRef 与新能源 HV 安全不变量。
- OR-Tools CP-SAT 调度、独立验证器、审批 token 和 lease。
- 配件确诊门禁、VIN 兼容、BRING_BOTH、改诊补偿。
- MCP Gateway 的 scope、限流、熔断、参数、审计和 Trace。
- 运营 metric_id 白名单与 fact/inference/recommendation/scenario 分层。
- Repository 乐观锁、Outbox、Saga 和知识隔离区。
- 测试如何证明关键业务不变量。

## 质量要求

- 结论必须指向真实文件、类、函数或测试，不得从 README 推断不存在的实现。
- 明确区分默认本地实现、可选真实集成和生产设计；不得把模拟适配器写成已连接外部生产系统。
- 使用 Mermaid 展示总体架构、主业务时序、状态机和改诊补偿；图必须与代码一致。
- 解释关键设计的原因、失败路径和替代方案，不只罗列目录。
- 如果代码与文档有冲突，以代码和测试为准，并在 Wiki 中指出边界。

