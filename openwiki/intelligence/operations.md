---
type: 运营智能
title: 白名单指标与事实分层
description: 说明 OperationsAgent 如何将自然语言限制到 metric_id 白名单，并分离 fact、inference、recommendation 与 scenario。
tags: [operations, metrics, governance]
---

# 白名单指标与事实分层

`OperationsAgent.answer` 不生成 SQL，也不让模型选择任意数据面操作。它先用 `_resolve_metric` 在 `METRICS` 中按展示名或 aliases 匹配；匹配失败抛 `MetricNotAllowed`。当前白名单是 `workorder_count`、`closure_rate`、`first_time_fix_rate`、`sla_compliance`、`parts_fill_rate`。

`RoadMindService.query_operations` 要 `metrics:query`；当请求带 `scenario_delta` 时额外要 `metrics:simulate`。随后服务在 `operations_agent` trace 中传入 `repo.list()` 的本地工单副本。

| 输出层 | 字段/标签 | 语义 |
|---|---|---|
| fact | `fact.metric_id`、value、unit、sample_size、scope | 已按当前 ABAC 范围计算的值。 |
| inference | `hypothesis_not_fact` | 对样本量/进行中工单的低置信解释，不是事实。 |
| recommendation | `pending_approval` | 区域运营负责人待批准的行动建议，有 28 天观察窗口和停止条件。 |
| scenario | `what_if_not_fact` | 只在 `scenario_delta` 提供时计算的比例投影，明确不可当作发生事实。 |

非 admin 的 `_apply_abac` 只保留 `principal.region` 为 `south_china` 或等于工单 `location` 的记录；admin 看到全部。注意这只是演示 ABAC：地域字符串的比较不表示完整组织/数据权限模型。

指标口径也应按代码解释：首次修复率为已结案且 `replan_count == 0` 的比例；SLA 达成率目前以 `not degraded_mode` 近似；配件满足率为存在 `reserved_part_codes` 的全部工单比例。尤其 SLA 不应被表述成真实 24 小时计时系统。

`tests/test_operations_and_api.py:test_operations_separates_fact_inference_recommendation_and_scenario` 固定验证四层标签和模板引用；`test_operations_rejects_free_form_sql` 验证 `select * from users` 被拒绝。修改指标应同时增补 `METRICS`、解析逻辑、计算分支、权限/输出说明和对应测试，不能仅增加自然语言提示词。

扩展区域规则时，规范修改面是 `Principal.region` 的输入/认证来源、`OperationsAgent._apply_abac` 的选择条件、返回 `fact.scope` 与 `sample_size` 的解释，以及覆盖 admin/非 admin 可见集合的测试；若新增范围所需权限不同，还要改 `ROLE_SCOPES` 和 `RoadMindService.query_operations` 的 scope 检查。不要只替换地域字符串：事实层必须仍反映过滤后的记录，`inference`、`recommendation`、`scenario` 的非事实标签和当前输出形状也必须保持，除非显式进行 API 契约变更。
