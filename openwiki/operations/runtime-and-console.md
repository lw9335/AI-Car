---
type: 运行与演示
title: 本地运行、容器与静态控制台
description: 说明 Uvicorn、Docker、Compose infra profile、示例环境变量和静态控制台的实际边界。
tags: [runtime, docker, console]
---

# 本地运行、容器与静态控制台

运行入口是 `roadmind.main:app`。开发可使用：

```bash
python -m venv .venv
./.venv/bin/pip install -e '.[dev]'
./.venv/bin/uvicorn roadmind.main:app --reload
```

`Dockerfile` 基于 `python:3.12-slim`，只复制 `pyproject.toml`、`README.md`、`src`，安装基础依赖并以 `uvicorn roadmind.main:app --host 0.0.0.0 --port 8000` 启动。它的 healthcheck 请求 `/api/v1/health`。`docker compose up --build` 启动 app 并将 8000 映射到宿主机。

## 声明基础设施与实际默认路径

`docker-compose.yml` 的 postgres、redis、neo4j 都在 `infra` profile，默认 `docker compose up --build` 不启动它们。即使显式启用 profile，`RoadMindService.__init__` 仍构造 `InMemoryWorkOrderRepository`、内存 lease、内存 Outbox 和 `MemorySaver`；没有读取连接串或初始化 PostgreSQL/Redis/Neo4j 客户端的代码。因此这些容器是生产替换/架构意图，不是演示主请求路径的已连接依赖。

`.env.example` 含 `ROADMIND_ENV`、日志及 LangSmith/OpenAI 占位变量；当前源码没有用 settings 类读取它们。`DeepAgentsParentFactory` 仅在调用时惰性导入 `deepagents`，基础服务也不读取 `OPENAI_API_KEY`。保留空 key 的样例可用于未来配置，但不能把配置文件写成已启用 LangSmith 或 LLM。

## 静态控制台

`main.py` 将 `src/roadmind/static` 挂到 `/`，所以 `/` 是 HTML 控制台，API 仍在 `/api/v1`。`tests/test_operations_and_api.py:test_health_and_static_console` 验证 health 和首页可用。控制台用于演示请求和角色切换；身份边界仍是请求头构成的 demo `Principal`，不是登录系统。对接口、角色和响应脱敏规则，查[API 参考](../reference/api-and-validation.md)。

## 验证与部署提醒

本地最小检查：`pytest tests/test_operations_and_api.py -q`，随后访问 `http://127.0.0.1:8000/docs` 查看 FastAPI 生成的交互契约。生产化前至少需要替换内存适配器、实现真实身份认证与密钥管理、持久 checkpoint、外部事件投递和部署级限流；这些能力并未由当前 Compose 定义自动获得。
