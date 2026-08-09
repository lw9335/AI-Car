# NemoClaw 总控 Agent 运行契约

RoadMind 只把交互式总控 Agent 放入 NemoClaw/OpenShell。诊断、调度、配件、运营、
MCP Gateway、API、PostgreSQL 和 Redis 继续由常规容器平台管理。

## 镜像边界

`Dockerfile.agent` 构建独立的 `roadmind-enterprise-assistant` Harness：

- Deep Agents 负责开放式任务规划与会话执行；
- 只通过远程 MCP Gateway 读取企业能力；
- 写操作不暴露给模型，继续走 RoadMind 审批 API；
- 不挂载业务数据库凭据；
- 模型请求通过 NemoClaw/OpenShell 的 `inference.local` 路由。

## 必要环境变量

```text
ROADMIND_ENV=production
MCP_GATEWAY_URL=https://mcp.example.com/mcp
JWT_SECRET=<与业务平台一致的签名密钥>
ASSISTANT_MODE=deep_agents
ASSISTANT_BASE_URL=https://inference.local/v1
ASSISTANT_API_KEY=<OpenShell 管理的占位凭据>
ASSISTANT_MODEL=<NemoClaw 配置的模型 ID>
```

正式接入 NemoClaw 托管 MCP 前，RoadMind MCP Gateway 需要提供标准 HTTPS
Streamable HTTP 地址。当前 Compose 内部的 `http://mcp-gateway:8001/mcp` 只用于本地开发。

## 本地镜像验证

```powershell
docker build -f Dockerfile.agent -t roadmind-agent-harness:dev .
```

`/health` 是沙箱健康检查，`/v1/chat` 和 `/v1/conversations/{id}` 是 Harness
内部服务接口。对外认证、渠道接入和流式传输仍由 RoadMind Assistant API 负责。
