---
type: 领域模型
title: L0 工单、版本与状态边界
description: 定义 ServiceRequestCreate、WorkOrder、TaskPlan、审批与证据模型，以及线程、版本、PII 和状态机不变量。
tags: [domain, work-order, state-machine]
---

# L0 工单、版本与状态边界

`domain/models.py` 把 `WorkOrder` 定义为 L0 业务真源。`ServiceRequestCreate` 是创建输入；服务将姓名和手机号写入 `PiiVault`，工单只存 `reporter_pii_ref`。随后 `WorkOrder.model_validator:set_thread_id` 保证 `thread_id` 缺省时等于 `service_request_id`，因此同一工单的计划、时间线及可选 LangGraph 配置可以使用同一个稳定键。

## 四层记忆/数据边界

| 层 | 载体 | 可放内容 | 不变量 |
|---|---|---|---|
| L0 工单状态 | `WorkOrder` 与仓储 | 车辆、症状、DTC、诊断、候选、预占、审批、计划、时间线 | 是 Agent 可见的业务协调状态，但不含直接联系人 PII。 |
| 任务计划 | `TaskPlan`、`TaskItem` | 域、动作、依赖、任务状态、结果、`plan_version` | Parent 生成；改诊冻结旧版本而非原地伪造历史。 |
| 隐私隔离 | `PiiVault` | `reporter_name`、`reporter_phone` | 工单只存引用；`reveal(..., authorized=True)` 才允许读取。 |
| 图检查点 | `NativeApprovalWorkflow` 的 `MemorySaver` | 独立 interrupt/resume 示例状态 | 进程内、非主工单审批真源；重启即丢失。详见[履约、改诊和恢复](../workflow/fulfillment-replan.md)。 |

这不是通用长期记忆系统：语料 `knowledge/corpus.py:DOCUMENTS` 是版本化只读示例知识，结案案例只被标成隔离候选，尚未写回检索库。

## 关键对象与双版本语义

- `version`：由 `state_machine.transition` 每次合法状态转移递增。`transition` 同时写 `updated_at` 并追加 `status.changed`；仓储 `save` 也在真正存储前刷新 `updated_at`，因此任何成功服务写入都具有新的更新时间。`RoadMindService` 读出时保存 `expected_version`，仓储拒绝陈旧写入；调用方收到冲突后必须重新读取，不可把旧副本再次保存。
- `plan_version`：`TaskPlan` 的流程代际。首版为 1；`report_mismatch` 新建 `old + 1` 的计划，并将旧号附加到新计划的 `frozen_versions`。该历史表示旧任务图被冻结，新的 `tasks` 从 Parent 模板重新开始；它不等于工单 `version`。改诊会保留 `replan_count`、`timeline` 和冻结版本历史，但清空已选资源、已预占件、两类候选及诊断的确认字段，随后从 `REDIAGNOSIS_REQUIRED` 再进 `DIAGNOSING`。
- `Approval`：包含随机 `token`、请求角色、状态和决定者。诊断确认与调度派工各有审批对象；API 仅让 dispatcher/admin 看到 token。
- `EvidenceRef`：证据 ID、来源、品牌、可选车型、版本、评分、片段。`DiagnosisPackage` 同时保存证据列表和每个假设引用的 ID。

```mermaid
stateDiagram-v2
  [*] --> reported
  reported --> triaged
  triaged --> diagnosing
  diagnosing --> waiting_expert
  diagnosing --> manual_takeover
  waiting_expert --> diagnosis_confirmed
  waiting_expert --> rediagnosis_required
  diagnosis_confirmed --> fulfilling
  fulfilling --> ready_for_service
  fulfilling --> rediagnosis_required
  ready_for_service --> in_service
  in_service --> waiting_close_approval
  in_service --> rediagnosis_required
  waiting_close_approval --> closed
  rediagnosis_required --> diagnosing
  rediagnosis_required --> manual_takeover
  manual_takeover --> diagnosing
  manual_takeover --> waiting_close_approval
```

该图是 `ALLOWED_TRANSITIONS` 的许可边，不代表每个状态都由一个公开端点直接可达。例如 `close_order` 在一次服务调用内依次经过 `WAITING_CLOSE_APPROVAL` 和 `CLOSED`，目前没有单独的关闭审批 token。

## 修改守则与验证

不要直接改 `order.status`：使用 `transition(order, target, actor, reason)` 才会验证边、递增版本并记录 `status.changed`。新增状态必须同时调整 `ALLOWED_TRANSITIONS`、服务前置条件、API 行为和测试。

`tests/test_domain.py` 证明：创建时线程键相同且 JSON 不含手机号；Vault 需要显式授权；不能从 `TRIAGED` 跳到 `CLOSED`；陈旧 `expected_version` 抛 `OptimisticLockError`；无关角色不能写配件。完整状态落点见[工单生命周期](../workflow/work-order-lifecycle.md)。
