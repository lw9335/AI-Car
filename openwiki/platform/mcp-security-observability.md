---
type: 平台边界
title: MCP Gateway、权限、审计与 Trace
description: 说明所有工具调用的 scope、参数、限流、熔断、脱敏审计和父子 Trace 边界，并列出本地 mock 工具事实。
tags: [mcp, security, observability]
---

# MCP Gateway、权限、审计与 Trace

`McpGateway.invoke` 是工具调用的统一控制点。工具在 `mcp/tools.py:build_gateway` 注册为 `ToolSpec`；每个规格声明名称、必需 scope、handler、必需参数、风险和幂等提示。HTTP 端的 `Principal` 由请求头构造，`ROLE_SCOPES` 定义角色能力；`ADMIN` 的 `*` 可绕过具体 scope。

## 调用顺序与审计

1. 查找工具，不存在抛 `ToolNotFound`。
2. `require_scope`；按 user ID 在一分钟滑动窗口内做限流，默认 120 次。
3. 检查工具熔断窗口；连续 handler 失败 3 次，工具 30 秒内 `CircuitOpen`。
4. 校验 `required_params` 存在，再开始 tool span。
5. 执行 handler；成功清零该工具失败计数，失败则记录错误；无论结果都追加审计记录。

审计项带 actor、role、service_request_id、risk、时间和参数；`phone`、`token`、`approval_token`、`password` 被替换为 `***`。这只处理顶层精确键，新增嵌套敏感结构时必须扩展 `_redact`。`TraceRecorder.span` 用 `ContextVar` 建父子关系；`run_diagnosis` 的 `intelligent_maintenance_agent` span 内调用 telemetry，因此工具 span 继承 parent ID。

## 工具现实边界

`vehicle.decode_vin` 返回 `source: mock_dms_adapter`，`telemetry.get_live_signals` 返回 `source: mock_iot_adapter`，`map.calculate_eta` 返回 `source: mock_map_adapter`。这些是可运行的本地 handler，而非 DMS/IoT/地图生产集成。库存和资源 handler 会调用本地 `PartsAgent`、`DispatchAgent`；知识、DTC、通知等若只用 lambda 返回示例结构，同样不可声称已接外部系统。

风险为 `sensitive_write` 的 `workflow.assign_resource` 和 `inventory.reserve` 仍需上游服务的审批/候选门禁；Gateway 不替代业务不变量。相关门禁见[履约工作流](../workflow/fulfillment-replan.md)。

## API 可见性与验证

`GET /tools` 要 `workorder:read`，只展示元数据；`GET /tool-audit` 传 `"*"` 给 `require_scope`，因此只有 admin 可读；`GET /traces` 要工单读权限且可按 `service_request_id` 筛选。`tests/test_diagnosis_and_retrieval.py:test_tool_call_is_audited_and_parented_under_agent_trace` 证明 VIN/telemetry 调用入审计且工具 span 有父节点；`tests/test_operations_and_api.py:test_api_rbac_and_token_redaction` 证明非授权写入得 403，且 information officer 的审批 token 被遮蔽。
