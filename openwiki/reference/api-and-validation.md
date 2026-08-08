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
| `POST /{id}/service/start`、`/close` | 无、`ClosureRequest` | `service:execute` | `start_service`、`close_order` |
| `POST /{id}/mismatch` | `DiagnosisMismatch` | `diagnosis:run` | `report_mismatch` |
| `POST /operations/query` | `OpsQuery` | `metrics:query`，情景另要 simulate | `query_operations` |
| `GET /tools`、`/traces`、`/tool-audit` | 无 | read、read、admin | Gateway/Trace 读取 |

`present_order` 序列化后对非 dispatcher/admin 的每一个 `Approval.token` 置 `***`。这只保护响应显示；服务内部仍持 token，且 token 本身没有过期字段或一次性消费标记。

## 错误映射

`main.py:create_app` 统一映射：缺工单 404、权限 403、非法状态与乐观锁 409、`ValueError` 业务规则 422。Pydantic 输入校验由 FastAPI 产生其默认 422。MCP 的 `RateLimitExceeded`、`CircuitOpen` 等目前没有专用映射，调用者不应假定稳定的错误 JSON。

## 测试即不变量清单

| 关注点 | 聚焦测试 | 证明内容 |
|---|---|---|
| L0/PII/版本/状态 | `tests/test_domain.py` | 同 ID thread、PII 不进工单、显式 Vault 授权、跳转拒绝、乐观锁、scope 拒绝。 |
| 初诊与安全 | `tests/test_diagnosis_and_retrieval.py` | 模式路由、版本化证据、未确诊、HV 门禁、无 DTC 低置信、工具审计/trace 父子。 |
| 主履约与改诊 | `tests/test_full_workflow.py` | 并行候选 join、审批 token、HV 调度、库存/lease 补偿、隔离结案、interrupt 示例。 |
| 运营与 API | `tests/test_operations_and_api.py` | 四层运营输出、拒绝自由 SQL、health/静态页、RBAC 与 token 脱敏。 |

窄验证分别用 `pytest tests/test_domain.py -q`、`pytest tests/test_diagnosis_and_retrieval.py -q`、`pytest tests/test_full_workflow.py -q`。跨域改动运行 `pytest`；风格检查使用 `ruff check .`。这些命令来自 `pyproject.toml` 的 pytest 配置。
