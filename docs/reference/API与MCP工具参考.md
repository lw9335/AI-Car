# Reference：API 与 MCP 工具

## 身份请求头

| Header | 示例 | 说明 |
|---|---|---|
| `X-User-Id` | `dispatcher-01` | 审计主体 |
| `X-Role` | `dispatcher` | Role 枚举值 |
| `X-Region` | `south_china` | ABAC 示例属性 |

## API

| 方法 | 路径 | scope | 主要前置条件 |
|---|---|---|---|
| GET | `/api/v1/health` | 无 | 无 |
| POST | `/api/v1/work-orders` | workorder:create | VIN 合法 |
| GET | `/api/v1/work-orders` | workorder:read | 无 |
| GET | `/api/v1/work-orders/{id}` | workorder:read | 工单存在 |
| POST | `/{id}/diagnose` | diagnosis:run | TRIAGED 或 REDIAGNOSIS_REQUIRED |
| POST | `/{id}/expert-confirm` | diagnosis:confirm | WAITING_EXPERT、diagnosis_id 匹配 |
| POST | `/{id}/dispatch/approve` | dispatch:approve | FULFILLING、token/候选有效 |
| POST | `/{id}/parts/reserve` | parts:reserve | FULFILLING、候选兼容且有库存 |
| POST | `/{id}/service/start` | service:execute | READY_FOR_SERVICE |
| POST | `/{id}/mismatch` | diagnosis:run | 履约或维修中 |
| POST | `/{id}/close` | service:execute | IN_SERVICE |
| POST | `/{id}/close/approve` | service:close_approve | WAITING_CLOSE_APPROVAL、token 有效 |
| POST | `/operations/query` | metrics:query / simulate | question 能映射 metric_id |
| GET | `/tools` | workorder:read | 无 |
| GET | `/tool-audit` | admin | 无 |
| GET | `/traces` | workorder:read | 可选 service_request_id |
| POST | `/mcp`（MCP 服务） | 按工具动态校验 | MCP 2026-07-28 JSON-RPC 请求 |

完整 schema 以运行时 `/docs` 为准。

## MCP Streamable HTTP

RoadMind 实现 MCP `2026-07-28` 的无会话请求/响应模式。每个 `POST /mcp` 请求必须携带：

- `Authorization: Bearer ...`（测试环境也可使用 `X-Role` / `X-User-Id`）；
- `Accept: application/json, text/event-stream`；
- `MCP-Protocol-Version: 2026-07-28`；
- `Mcp-Method`，调用工具时还必须有与 `params.name` 相同的 `Mcp-Name`；
- `params._meta` 中的协议版本、clientInfo 和 clientCapabilities。

支持 `server/discover`、`tools/list`、`tools/call`。`tools/list` 仅返回当前身份有权调用的工具，并提供确定顺序、`inputSchema`、缓存 TTL 和 private cache scope；`tools/call` 同时返回文本 content 和 structuredContent。

Compose 中 `/api/*` 路由到业务 API，`/mcp` 路由到独立 `mcp-gateway:8001`。业务 API 使用 `RemoteMcpGateway` 发起相同的标准协议请求；远程限流、熔断和业务错误会还原为 API 的 429、503 和 422 语义。

## MCP Gateway 执行顺序

```text
HTTP header/body routing consistency
-> tool existence
-> principal scope
-> per-user rate limit
-> circuit state
-> JSON Schema params
-> trace span
-> handler
-> failure counter/circuit
-> redacted audit record
```

限流窗口、失败计数和熔断状态都在同一网关锁下更新，避免并发请求丢计数。审计脱敏递归遍历对象和数组，不只处理第一层字段。

## 已注册工具

### 车辆池

- `vehicle.decode_vin`：建单时验证 VIN。
- `vehicle.get_profile`：读取车辆配置。
- `telemetry.get_live_signals`：读取工单遥测。
- `dtc.get_definition`：按 OEM 源读取 DTC 定义。

### 知识池

- `knowledge.search_manual`
- `knowledge.search_case`
- `case.create_candidate`：只创建隔离区案例候选。

### 调度池

- `workflow.assign_resource`：敏感写、非幂等，要求审批 scope。
- `workflow.release_resource`：改诊 Saga 的资源租约补偿，仍经过网关审计。
- `map.calculate_eta`
- `notification.send`

### 配件池

- `inventory.search_available`
- `inventory.reserve`：敏感写；同一工单、同一配件集合的重试幂等，不同集合会返回业务冲突。
- `inventory.release`
- `pricing.calculate_quote`

### 运营池

- `metrics.run_template`

### 通用

- `workorder.get_history`
- `expert.request_review`

## 错误语义

- 403 `permission_denied`：角色/scope 不允许。
- 404 `work_order_not_found`：主键不存在。
- 409 `invalid_transition`：状态机非法跳转。
- 409 `optimistic_lock`：版本冲突，需要重新读取。
- 429 `rate_limit_exceeded`：调用方超过窗口配额，响应带 `Retry-After: 60`。
- 503 `upstream_circuit_open`：上游工具连续失败后熔断，调用方应退避或降级。
- 422 `business_rule`：候选、token、库存、指标等业务校验失败。
- 422 FastAPI validation：请求 schema 不合法。

`version` 在 Repository 每次成功保存时递增，而不是仅在状态转换时递增。因此调度审批和配件预占即使都停留在 `FULFILLING`，也不能用同一旧版本相互覆盖。
