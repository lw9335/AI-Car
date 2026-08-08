# RoadMind AI 商用车售后服务协同平台

RoadMind 是一个可运行、可测试的商用车售后维修知识与服务协同样板。项目将售后服务总控、智能维修、资源调度、配件供应链和运营决策拆成边界清晰的领域能力，并用同一张 L0 工单作为业务真源。

它重点演示的不是“让大模型自由聊天”，而是如何把 Agent 放进有状态、有证据、有审批、有补偿、有审计的业务系统：

- 一工单一线程：`thread_id = service_request_id`，Task Plan 与时间线随工单持久化。
- Parent + Workflow 分离：模糊理解和粗路由由 Parent 处理；并行履约、现场改诊和人工门禁进入显式 LangGraph。
- 初诊不等于确诊：所有诊断都携带 `evidence_refs`，专家确认后才允许推荐和预占配件。
- 调度保留人工决策：候选资源先过品牌、技能、服务模式和高压资质硬约束，再由调度员携审批令牌派工。
- 失败可恢复：现场改诊冻结旧计划、释放人员租约和配件预占、递增 `plan_version`；超过阈值强制人工接管。
- 工具统一过 MCP Gateway：scope、参数校验、限流、熔断、审计和 Trace 在同一边界执行。
- 运营禁止自由 SQL：自然语言只映射到白名单 `metric_id`，事实、推断、建议和 What-if 明确分层。

## 运行方式

### Windows PowerShell

```powershell
./scripts/bootstrap.ps1
./scripts/run.ps1
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。API 文档位于 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

### 通用命令

```bash
python -m venv .venv
./.venv/bin/pip install -e '.[dev]'
./.venv/bin/uvicorn roadmind.main:app --reload
```

### Docker

```bash
docker compose up --build
```

## 演示主链路

1. 信息员创建服务请求，系统将手机号写入 PII Vault，只把引用放进工单。
2. 维修 Agent 按动力类型硬路由 Mode A/Mode B，执行品牌/车型/版本过滤后的混合检索。
3. 专家审核结构化初诊包。通过后，LangGraph 并行生成调度候选和配件候选。
4. 调度员使用审批令牌预占人员；配件管理员预占 VIN 兼容件。两者 Join 后才进入现场服务。
5. 可选择正常结案，或模拟现场改诊，观察 Saga 补偿和 `plan_version` 递增。
6. 运营负责人以自然语言查询白名单指标并运行 What-if。

## 代码地图

```text
src/roadmind/
├── agents/          # Parent、维修、调度、配件、运营领域 Agent
├── api/             # FastAPI 路由、角色身份与错误边界
├── application/     # 跨领域应用服务与业务闭环
├── domain/          # 工单模型、状态机、RBAC 权限
├── infra/           # Repository、PII Vault、Outbox、Saga、Trace
├── knowledge/       # 版本化示例知识与 Hybrid RAG/RRF
├── mcp/             # 工具注册表与统一 MCP Gateway
├── workflows/       # LangGraph 并行 Join、改诊重规划、Interrupt/Resume
└── static/          # 多角色演示控制台
```

完整的教程、操作手册、参考资料、架构解释和面试学习资料位于 `docs/`；OpenWiki 自动生成的代码库知识库位于 `openwiki/`。

## 质量命令

```bash
pytest
pytest --cov=roadmind --cov-report=term-missing
ruff check .
```

## 真实边界

仓库默认使用内存适配器和脱敏示例数据，以便无密钥运行。PostgreSQL、Redis、Kafka、OpenSearch、Neo4j、DMS/ERP/WMS/IoT 和 LangSmith 在架构中以端口或 Gateway 边界体现，生产化时替换对应适配器。默认 Parent 是与 LLM Parent 相同结构化契约的确定性实现；安装 `agent` extra 并配置模型后，可通过 `DeepAgentsParentFactory` 创建真实 Deep Agents Parent。

不要把示例数据、演示评测值或未接入的外部系统描述成已在真实生产环境上线。面试口径详见 `docs/interview/真实性边界与回答口径.md`。

