---
type: 数据可靠性
title: 乐观锁、Outbox、Saga 与知识隔离区
description: 说明默认内存持久化的一致性契约、事件投递、补偿模型、PII 隔离以及结案知识候选的非发布边界。
tags: [reliability, repository, outbox, saga]
---

# 乐观锁、Outbox、Saga 与知识隔离区

默认 `InMemoryWorkOrderRepository` 是以 `RLock` 和 `deepcopy` 实现的测试适配器，目标是保留未来 PostgreSQL 适配器应遵守的契约，而不是提供进程外持久化。`get`、`create`、`save` 都复制对象，避免调用方绕过仓储修改内部状态；`save` 比较 `expected_version` 与当前工单 `version`，不相等即抛 `OptimisticLockError`。

服务方法先取工单与 `expected = order.version`，再通过 `transition` 修改状态，最后保存。状态转移自身增加 `version`，所以并发请求必须重新读取并重试/告知冲突，不能吞掉 409。

## Outbox 与 Saga

`TransactionalOutbox.append` 在创建时加入 `service_request.created`，结案时加入 `workorder.closed`。后者 payload 只有 `service_request_id` 与结案时的 `plan_version`。在 `close_order` 中，它在两个状态转移、任务/隔离时间线写入之后、`repo.save` 之前 append；因此当前内存实现并不保证“工单保存与 outbox append”原子提交，保存失败可能留下已 append 的消息，生产替换必须将两者纳入同一持久事务。

`pending` 返回 `delivered == false` 的消息；`deliver(publisher)` 在同一内存锁内顺序调用 publisher，**仅**在 publisher 正常返回后标记当前消息 delivered。若 publisher 抛异常，异常立即传播：当前消息未标记，仍会出现在 `pending`；后续消息不会在那次调用中处理，也仍待投递。现有仓库没有专门覆盖 publisher 失败投递的测试，`test_normal_closure_creates_quarantined_case_and_outbox` 只证明新结案消息初始处于 pending；为 `deliver` 或重试语义改动时应补充该失败回归测试。没有数据库事务、重试、去重消费者或消息代理，因此“Transactional”描述的是接口意图而非当前跨存储原子性。

通用 `Saga` 允许通过 `record(name, compensate)` 登记已完成步骤，并由 `compensate_all` 逆序执行。实际 mismatch 主路径没有创建 `Saga` 实例，而是将资源 lease 释放和配件库存释放封装为 `build_mismatch_replan_graph` 的补偿节点；原因与顺序见[履约、改诊和恢复](../workflow/fulfillment-replan.md)。不要在文档中把两者混为同一已执行机制。

## PII 与知识隔离

`PiiVault` 将直接标识信息保存在独立字典，工单仅保存 `pii_*` reference；读取必须传 `authorized=True`。这不是加密 Vault、审计系统或持久密钥管理实现，但它强制 Agent 可见 L0 状态不携带手机号。

结案创建 `knowledge.case_candidate_created` 时间线事件，且 `publication_status` 固定为 `quarantine_pending_quality_review`。没有将该案例写入 `knowledge/corpus.py:DOCUMENTS` 的代码路径，因而隔离区是防止未审核现场结论污染诊断知识的边界。发布流程、质量评审和索引更新仍是生产待实现的替换面。

## 证据与修改检查

`tests/test_domain.py:test_repository_optimistic_lock` 证明陈旧版本被拒绝；`test_create_order_uses_same_id_for_thread_and_hides_pii` 与 `test_pii_vault_requires_explicit_authorization` 证明引用隔离和显式读取；`tests/test_full_workflow.py:test_normal_closure_creates_quarantined_case_and_outbox` 验证隔离事件和 pending `workorder.closed`。改动仓储或事件语义时先运行这些测试，再运行完整 `pytest`。
