---
type: API 参考
title: HTTP API、角色与验证矩阵
description: 汇总真实 FastAPI 路由、输入模型、授权边界、错误映射和证明关键不变量的聚焦测试。
tags: [api, rbac, testing]
---

# HTTP API、角色与验证矩阵

路由前缀是 `/api/v1`。`principal_from_headers` 从 `X-User-Id`、`X-Role`、`X-Region` 构建 `Principal`，默认 role 是 `admin`，仅适合演示；没有 JWT、会话或外部身份校验。业务实现归属 `RoadMindService`，请以[工单生命周期](../workflow/work-order-lifecycle.md)为语义规范。

| 方法与路径 | 输入 | 最小 scope | 服务方法 |
|---|---|---|---|
| `POST /work-orders` | `ServiceRequestCreate` | `workorder:create` | `create_request` |
| `GET /work-orders`、`/{order_id}` | 无 | `workorder:read` | `list_orders`、`get_order` |
| `POST /{id}/diagnose` | 无 | `diagnosis:run` | `run_diagnosis` |
| `POST /{id}/expert-confirm` | `ExpertDecision` | `diagnosis:confirm` | `confirm_diagnosis` |
| `POST /{id}/dispatch/approve` | `DispatchApproval` | `dispatch:approve` | `approve_dispatch` |
| `POST /{id}/parts/reserve` | `PartsReservationRequest` | `parts:reserve` | `reserve_parts` |
| `POST /{id}/service/start`、`/close`、`/close/approve` | 无、`ClosureRequest`、`ClosureApproval` | `service:execute`、`service:execute`、`service:close_approve` | `start_service`、`close_order`、`approve_closure` |
| `POST /{id}/mismatch` | `DiagnosisMismatch` | `diagnosis:run` | `report_mismatch` |
| `POST /operations/query` | `OpsQuery` | `metrics:query`，情景另要 simulate | `query_operations` |
| `GET /tools`、`/traces`、`/tool-audit` | 无 | read、read、admin | Gateway/Trace 读取 |

`present_order` 序列化后仅对 requested role 与当前角色不匹配、且当前角色不是 admin 的 `Approval.token` 置 `***`；因此诊断、派工或结案的对应审批角色能看到自己的 token。它只保护响应显示；服务内部仍持 token，且 token 本身没有过期字段或一次性消费标记。

## 错误映射

`main.py:create_app` 统一映射：`WorkOrderNotFound` 与 `ToolNotFound` 为 404，权限为 403，非法状态与乐观锁为 409，`ValueError` 业务规则为 422；Pydantic 输入校验也由 FastAPI 产生默认 422。来自[MCP Gateway](../platform/mcp-security-observability.md)的 `RateLimitExceeded` 是 429、`error: rate_limit_exceeded` 且响应头固定 `Retry-After: 60`；`CircuitOpen` 是 503、`error: upstream_circuit_open`。这是已注册的 HTTP 契约，而 `ToolValidationError` 等其他 Gateway 例外仍没有专用处理器，不能据此推断其稳定错误 JSON。

## 测试即不变量清单

| 关注点 | 聚焦测试 | 证明内容 |
|---|---|---|
| L0/PII/版本/状态 | `tests/test_domain.py` | 同 ID thread、PII 不进工单、显式 Vault 授权、跳转拒绝、乐观锁、scope 拒绝。 |
| 初诊与安全 | `tests/test_diagnosis_and_retrieval.py` | 模式路由、版本化证据、未确诊、HV 门禁、无 DTC 低置信、工具审计/trace 父子。 |
| MCP 韧性与审计脱敏 | `tests/test_mcp_resilience.py` | 同一 actor 的一分钟限流、连续三次 handler 失败后熔断，以及嵌套字典/列表中 `phone` 与 `approval_token` 的递归脱敏。 |
| 主履约、结案与改诊 | `tests/test_full_workflow.py` | 并行候选 join、派工/结案审批 token、HV 调度、库存/lease 补偿、隔离结案、关闭拒绝回服务中、interrupt 示例。 |
| 运营与 API | `tests/test_operations_and_api.py` | 四层运营输出、拒绝自由 SQL、health/静态页、RBAC 与 token 脱敏；`test_api_maps_rate_limit_to_429_with_retry_after` 与 `test_api_maps_open_circuit_to_503` 分别锁定 Gateway 限流/熔断的消费者响应。 |

窄验证分别用 `pytest tests/test_domain.py -q`、`pytest tests/test_diagnosis_and_retrieval.py -q`、`pytest tests/test_mcp_resilience.py -q`、`pytest tests/test_full_workflow.py -q`。跨域改动运行 `pytest`；风格检查使用 `ruff check .`。这些命令来自 `pyproject.toml` 的 pytest 配置。
