# RoadMind AI 商用车售后服务协同平台

RoadMind 是一个可运行、可测试的商用车售后维修知识与服务协同样板。项目将售后服务总控、智能维修、资源调度、配件供应链和运营决策拆成边界清晰的领域能力，并用同一张 L0 工单作为业务真源。

它重点演示的不是“让大模型自由聊天”，而是如何把 Agent 放进有状态、有证据、有审批、有补偿、有审计的业务系统：

- 一工单一线程：`thread_id = service_request_id`，Task Plan 与时间线随工单持久化。
- 总控、Planner 与 Workflow 分离：开放式交互由总控处理，工单 Planner 生成受审计任务图，并行履约、现场改诊和人工门禁进入显式 LangGraph。
- 初诊不等于确诊：所有诊断都携带 `evidence_refs`，专家确认后才允许推荐和预占配件。
- 调度保留人工决策：候选资源先过品牌、技能、服务模式和高压资质硬约束，再由调度员携审批令牌派工。
- 失败可恢复：现场改诊冻结旧计划、释放人员租约和配件预占、递增 `plan_version`；超过阈值强制人工接管。
- 工具统一过 MCP Gateway：标准 MCP 2026-07-28 Streamable HTTP、scope、JSON Schema 参数校验、限流、熔断、审计和 Trace 在同一边界执行。
- 运营禁止自由 SQL：自然语言只映射到白名单 `metric_id`，事实、推断、建议和 What-if 明确分层。

## 推荐部署（服务器 / Docker Compose）

```bash
cp .env.example .env
# 编辑 .env：必须填写 JWT_SECRET、DEMO_PASSWORD、POSTGRES_PASSWORD、CORS_ORIGINS
# 可选：填写 OPENROUTER_API_KEY 与 OPENROUTER_MODEL（OpenRouter 免费英伟达模型）
docker compose up -d --build
```

浏览器打开 `http://YOUR_SERVER:80`。演示账号用户名为角色名（如 `admin` / `expert`），密码由 `DEMO_PASSWORD` 指定。生产模式会拒绝示例密钥和默认密码。

服务组成：

| 服务 | 说明 |
|------|------|
| `web` | React SPA（nginx），分别反代 `/api` 与 `/mcp` |
| `api` | FastAPI 业务服务：工单、状态机、Planner、审批与 Workflow 编排 |
| `mcp-gateway` | 独立 FastAPI MCP 服务：工具发现、授权、限流、熔断、审计与执行 |
| `postgres` | 工单 / PII / Outbox / 用户持久化 |
| `redis` | 资源短租约 |

API 文档：`http://YOUR_SERVER/docs`；MCP 文档：`http://YOUR_SERVER/mcp/docs`；协议端点：`POST http://YOUR_SERVER/mcp`。

## 本地开发

### 后端（内存适配器，无需 Docker）

```powershell
./scripts/bootstrap.ps1
$env:ROADMIND_ENV = "local"
./scripts/run.ps1
```

默认本地模式为了调试方便使用进程内 Gateway。需要按生产拓扑启动两个进程进行协议联调时：

```powershell
# 终端 1：独立 MCP Gateway
$env:ROADMIND_ENV = "local"
./scripts/run-mcp.ps1

# 终端 2：业务 API 通过远程 MCP Client 调用 Gateway
$env:ROADMIND_ENV = "local"
$env:MCP_GATEWAY_URL = "http://127.0.0.1:8001/mcp"
./scripts/run.ps1
```

完整跨服务业务闭环还要求两个进程连接同一 PostgreSQL 和 Redis；因此完整分离演示优先使用 Docker Compose。仅使用内存适配器时，请继续使用默认进程内 Gateway，避免产生两份临时状态。

### 前端

```powershell
cd web
npm ci
npm run dev
```

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。Vite 会把 `/api` 代理到 `8000`。

### 通用命令

```bash
python -m venv .venv
./.venv/bin/pip install -e '.[dev]'
ROADMIND_ENV=local ./.venv/bin/uvicorn roadmind.main:app --reload
```

## 演示主链路

1. 使用对应角色登录（或 `admin` 全权限演示）。
2. 信息员创建服务请求，系统将手机号写入 PII Vault，只把引用放进工单。
3. 诊断能力服务按动力类型硬路由 Mode A/Mode B，执行品牌/车型/版本过滤后的混合检索。
4. 专家审核结构化初诊包。通过后，LangGraph 并行生成调度候选和配件候选。
5. 调度员使用审批令牌预占人员；配件管理员预占 VIN 兼容件。两者 Join 后才进入现场服务。
6. 可选择正常结案，或模拟现场改诊，观察 Saga 补偿和 `plan_version` 递增；超过重规划阈值后可人工接管恢复。
7. 运营负责人以自然语言查询白名单指标并运行 What-if。

## 代码地图

```text
src/roadmind/
├── agents/          # 兼容目录：工单规划器与确定性领域能力（后续迁移到 capabilities/）
├── api/             # FastAPI 路由、JWT 身份与错误边界
├── application/     # 跨领域用例与领域能力端口
├── auth/            # 用户种子与 JWT
├── domain/          # 工单模型、状态机、RBAC 权限
├── infra/           # Repository、PII、Outbox、Redis 租约、Trace
├── knowledge/       # 版本化示例知识与 Hybrid RAG/RRF
├── mcp/             # 独立服务入口、远程 Client、Gateway 与标准 MCP 协议适配
├── workflows/       # LangGraph 并行 Join、改诊重规划、Interrupt/Resume
├── bootstrap.py     # API 组合根：选择 PostgreSQL、Redis、MCP 与领域实现
└── settings.py      # 环境配置
web/                 # React + Vite SPA
```

完整的教程、操作手册、参考资料、架构解释和面试学习资料位于 `docs/`；OpenWiki 自动生成的代码库知识库位于 `openwiki/`。

## 质量命令

```bash
pytest
pytest --cov=roadmind --cov-report=term-missing
ruff check src tests
ruff format --check src tests
cd web && npm ci && npm run typecheck && npm run build
```

## 真实边界

- **已接入（Compose 默认）**：独立 `api` / `mcp-gateway` 服务、远程 MCP Client、PostgreSQL 工单持久化、Redis 资源租约、JWT 登录鉴权、OpenRouter 工单 Planner（有 key 时）。
- **仍为适配器边界**：Kafka Outbox 中继、Neo4j 故障图、OpenSearch、真实 DMS/ERP/WMS/IoT、LangSmith 云上报。
- 无 `OPENROUTER_API_KEY` 时自动回退确定性工单 Planner；`ROADMIND_ENV=test` 使用内存适配器并允许 Header 鉴权以便 pytest。

不要把示例数据、演示评测值或未接入的外部系统描述成已在真实生产环境上线。面试口径详见 `docs/interview/真实性边界与回答口径.md`。

## 上线前你需要填写

见 [`.env.example`](.env.example)：

- `JWT_SECRET`、`POSTGRES_PASSWORD`
- `CORS_ORIGINS` / 公网域名或 IP
- `OPENROUTER_API_KEY`、`OPENROUTER_MODEL`（可选）
- 上线后修改 `DEMO_PASSWORD` 与各角色默认口令策略

## 企业总控 Agent

Deep Agents SDK 承担唯一的交互式总控 Agent。总控通过强类型 Supervisor 工具直接编排
诊断、调度、配件和运营四个业务 Agent；人工页面/API 也调用同一个 `RoadMindService`，
因此对话入口和人工入口不会形成两套业务真相。LangGraph 承担可恢复流程和并行 Join，
MCP Gateway 承担企业数据与外部系统工具的发现、鉴权和审计。

无模型凭据时，确定性 Runtime 仍可通过 `context.command` 执行相同业务能力。确诊、派工和
配件预留必须同时满足 `confirmed_actions`、角色权限、状态机和原有审批令牌，模型不能绕过门禁。
部署时将总控 Agent Harness 纳入 NemoClaw/OpenShell；四个业务 Agent、API 和数据基础设施
继续作为普通容器或 Kubernetes 工作负载，由总控通过应用命令/MCP 编排。

- 本地/集成入口：`POST /api/v1/assistant/chat`
- 独立 Harness 入口：`POST /v1/chat`（`Dockerfile.agent`，默认端口 `8010`）
- 总控实现：`assistant/runtime.py` + `assistant/supervisor.py`
- 工单规划契约：`workflows/task_planner.py`（不是交互总控）
- NemoClaw 运行约束：[`docs/how-to/NemoClaw总控Agent运行契约.md`](docs/how-to/NemoClaw总控Agent运行契约.md)
