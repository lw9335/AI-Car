---
type: 快速开始
title: RoadMind 代码知识库导航
description: 面向 Python 与 Agent 工程师的 RoadMind 架构、工单闭环、安全门禁和验证入口导航。
tags: [quickstart, navigation, roadmind]
---

# RoadMind 代码知识库导航

RoadMind 是一个默认可离线运行的商用车售后编排样板：FastAPI 将请求交给 `RoadMindService`，以一张 L0 `WorkOrder` 协调证据优先诊断、人工确诊、并行调度/配件履约、现场改诊和结案。默认实现是内存状态、确定性 Agent 和 mock 外部 adapter；不要将其描述成已连接生产 DMS、IoT、库存、数据库或 LLM。

## 先读什么

- [总体架构与组合根](architecture/overview.md)：入口、分层、默认装配和真实边界。
- [L0 工单、版本与状态边界](domain/work-order.md)：`thread_id`、`version`/`plan_version`、Task Plan、PII 与状态机。
- [从 ServiceRequestCreate 到 WorkOrder 结案](workflow/work-order-lifecycle.md)：主 API 调用顺序和失败路径。
- [并行履约、改诊补偿与 LangGraph 恢复](workflow/fulfillment-replan.md)：fan-out/join、CP-SAT、token、lease、BRING_BOTH、Saga、interrupt/resume 的实际边界。
- [证据优先诊断与 Hybrid Retriever](intelligence/diagnosis-retrieval.md)：初诊/确诊、HV 安全和 RRF 检索。
- [MCP Gateway、权限、审计与 Trace](platform/mcp-security-observability.md)：工具防线。
- [乐观锁、Outbox、Saga 与知识隔离区](platform/data-reliability.md)：一致性与结案知识边界。
- [白名单指标与事实分层](intelligence/operations.md)：运营数据治理。
- [HTTP API、角色与验证矩阵](reference/api-and-validation.md)：请求入口与测试索引。
- [本地运行、容器与静态控制台](operations/runtime-and-console.md)：启动和部署边界。

## 按工程意图定位

| 变更意图 | 先读页面 | 源码入口/符号 | 聚焦测试 | 最小验证 |
|---|---|---|---|---|
| 新增或调整工单状态 | [领域模型](domain/work-order.md) | `ALLOWED_TRANSITIONS`、`transition`、`RoadMindService` | `test_domain.py` | `pytest tests/test_domain.py -q` |
| 修改从报修到结案流程 | [主生命周期](workflow/work-order-lifecycle.md) | `RoadMindService.create_request` 到 `.close_order` / `.approve_closure` | `test_full_workflow.py` | `pytest tests/test_full_workflow.py -q` |
| 改诊/补偿/恢复 | [履约与改诊](workflow/fulfillment-replan.md) | `report_mismatch`、`build_mismatch_replan_graph` | `test_mismatch_freezes_plan_and_compensates` | 同上 |
| 改检索或诊断安全 | [诊断与检索](intelligence/diagnosis-retrieval.md) | `DiagnosisAgent`、`HybridRetriever.search` | `test_diagnosis_and_retrieval.py` | `pytest tests/test_diagnosis_and_retrieval.py -q` |
| 改调度/配件策略 | [履约与改诊](workflow/fulfillment-replan.md) | `DispatchAgent`、`PartsAgent` | 履约与 EV 测试 | `pytest tests/test_full_workflow.py -q` |
| 新增 MCP 工具 | [MCP 平台](platform/mcp-security-observability.md) | `ToolSpec`、`build_gateway` | 审计/RBAC 测试 | `pytest tests/test_diagnosis_and_retrieval.py -q` |
| 新增运营指标 | [运营智能](intelligence/operations.md) | `METRICS`、`_calculate` | `test_operations_and_api.py` | `pytest tests/test_operations_and_api.py -q` |
| 替换本地基础设施 | [数据可靠性](platform/data-reliability.md) | repository、outbox、vault、trace | 领域与全流程测试 | `pytest` |

## 核心概念速记

- **L0 工单**是跨 Agent 的唯一协调状态，`thread_id = service_request_id`；直接 PII 不在其中。
- **初诊不等于确诊**：证据和候选件可以在初诊出现，但专家确认码是履约和配件候选的门槛。
- **Parent 规划，Workflow 执行**：Parent 生成任务依赖；LangGraph 显式处理并行 join 和改诊补偿。诊断、派工与结案审批都以 `WorkOrder.approvals` 中的 token 为业务真源；`NativeApprovalWorkflow` 只证明内存 checkpoint 的 interrupt/resume，不是主审批实现。
- **新能源安全是硬约束**：诊断 SOP 禁止远程带电操作，调度必须 `hv_certified`。
- **事实必须可追溯**：工具走 Gateway，运营问题映射白名单指标，结案知识先隔离而不直接回灌。

## 验证与 Backlog

跨系统改动运行 `pytest`，再运行 `ruff check .`。现有测试覆盖关键演示不变量，但默认内存适配器、mock 外部工具、无持久 LangGraph checkpoint、无真实身份认证和无案例发布流水线仍是明确的生产替换面，而非本 Wiki 的遗漏；对应源码边界已在上述页面记录。
