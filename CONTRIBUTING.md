# Contributing

## Local checks

Backend changes must pass:

```powershell
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
.\.venv\Scripts\python.exe -m pytest --cov=roadmind --cov-fail-under=80
```

Web changes must pass:

```powershell
Set-Location web
npm ci
npm run typecheck
npm run build
```

Container or configuration changes must also pass:

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

## Architecture rules

- Domain code must not import API, infrastructure, MCP, or deployable entrypoints.
- Application use cases depend on protocols; concrete adapters are selected at a composition root.
- Agents may discover tools through MCP, but tool descriptions never grant authorization.
- Sensitive writes require an existing business approval flow and an idempotency strategy.
- Generated OpenWiki pages are refreshed by automation and should not be edited by hand.

## Pull requests

- Keep one behavior change per pull request.
- Add failure-path tests before changing high-risk workflow or approval behavior.
- Update source documentation and contracts when public behavior changes.
- Never commit `.env`, model credentials, customer data, or access tokens.
