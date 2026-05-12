# Docker 生产部署

本文档说明如何把当前 `FastAPI + LangGraph + PostgreSQL/PGVector + Next.js` 应用构建为生产 Docker 镜像，并通过 `docker-compose.prod.yml` 在服务器启动。

生产 Compose 默认包含三个长期服务：

- `postgres`：PostgreSQL + PGVector，持久化到 Docker volume。
- `backend`：FastAPI，入口为 `app.main:app`，启动时会执行环境校验和数据库 readiness 检查。
- `frontend`：Next.js，使用 `/api` 代理到后端。

此外还有一次性 `migrate` 服务，会在后端启动前执行 `alembic -c alembic.ini upgrade head`。如果 migration 失败，后端不会启动。

## 本地构建镜像

先选择 Docker Hub namespace 和版本号：

```bash
export DOCKERHUB_NAMESPACE=your-dockerhub-namespace
export IMAGE_TAG=2026.05.12
```

构建后端和前端镜像：

```bash
docker build \
  -f backend/Dockerfile.prod \
  -t "${DOCKERHUB_NAMESPACE}/learning-assistant-backend:${IMAGE_TAG}" \
  ./backend

docker build \
  -f frontend/Dockerfile.prod \
  -t "${DOCKERHUB_NAMESPACE}/learning-assistant-frontend:${IMAGE_TAG}" \
  ./frontend
```

可选：给当前版本打 `latest` 标签：

```bash
docker tag \
  "${DOCKERHUB_NAMESPACE}/learning-assistant-backend:${IMAGE_TAG}" \
  "${DOCKERHUB_NAMESPACE}/learning-assistant-backend:latest"

docker tag \
  "${DOCKERHUB_NAMESPACE}/learning-assistant-frontend:${IMAGE_TAG}" \
  "${DOCKERHUB_NAMESPACE}/learning-assistant-frontend:latest"
```

## 推送镜像

Docker Hub：

```bash
docker login
docker push "${DOCKERHUB_NAMESPACE}/learning-assistant-backend:${IMAGE_TAG}"
docker push "${DOCKERHUB_NAMESPACE}/learning-assistant-frontend:${IMAGE_TAG}"
```

如果也打了 `latest`：

```bash
docker push "${DOCKERHUB_NAMESPACE}/learning-assistant-backend:latest"
docker push "${DOCKERHUB_NAMESPACE}/learning-assistant-frontend:latest"
```

GHCR 替代命令：

```bash
export GHCR_OWNER=your-github-owner
echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_OWNER}" --password-stdin

docker tag \
  "${DOCKERHUB_NAMESPACE}/learning-assistant-backend:${IMAGE_TAG}" \
  "ghcr.io/${GHCR_OWNER}/learning-assistant-backend:${IMAGE_TAG}"

docker tag \
  "${DOCKERHUB_NAMESPACE}/learning-assistant-frontend:${IMAGE_TAG}" \
  "ghcr.io/${GHCR_OWNER}/learning-assistant-frontend:${IMAGE_TAG}"

docker push "ghcr.io/${GHCR_OWNER}/learning-assistant-backend:${IMAGE_TAG}"
docker push "ghcr.io/${GHCR_OWNER}/learning-assistant-frontend:${IMAGE_TAG}"
```

使用 GHCR 时，服务器 `.env` 中的 `BACKEND_IMAGE` 和 `FRONTEND_IMAGE` 也要改为 `ghcr.io/...`。

## 服务器准备

把仓库中的 `docker-compose.prod.yml` 和 `.env.example` 放到服务器同一目录，然后创建生产 `.env`：

```bash
cp .env.example .env
```

至少替换以下变量：

```bash
DOCKERHUB_NAMESPACE=your-dockerhub-namespace
IMAGE_TAG=2026.05.12
BACKEND_IMAGE=your-dockerhub-namespace/learning-assistant-backend:2026.05.12
FRONTEND_IMAGE=your-dockerhub-namespace/learning-assistant-frontend:2026.05.12

POSTGRES_PASSWORD=replace-with-a-strong-postgres-password
DATABASE_URL=postgresql+psycopg://learning_user:replace-with-a-strong-postgres-password@postgres:5432/learning_assistant
LANGGRAPH_POSTGRES_URL=postgresql://learning_user:replace-with-a-strong-postgres-password@postgres:5432/learning_assistant

JWT_SECRET_KEY=replace-with-a-32-byte-or-longer-random-secret
CORS_ALLOW_ORIGINS=https://your-domain.example
AUTH_COOKIE_SECURE=true

MODEL_ACCESS_KEY=replace-with-model-access-key
GOOGLE_API_KEYS=replace-with-google-api-key
```

如果需要邮箱验证码注册，还要配置 `SMTP_*`。如果需要 LangSmith tracing、外部 MCP 或 Tavily 搜索，再配置对应可选变量。

生产建议通过 Nginx、Caddy 或云负载均衡把 HTTPS 流量代理到 `127.0.0.1:${FRONTEND_PORT}`。Compose 默认只把端口绑定到 `127.0.0.1`，避免数据库和后端 API 直接暴露到公网。
如果反向代理会把请求转发到后端 API，请把可信代理的 IP 或 CIDR 写入 `AUTH_TRUSTED_PROXY_IPS`，否则登录/验证码限流会按代理 IP 统计，并忽略 `X-Forwarded-For` / `X-Real-IP`。

## 启动

拉取镜像：

```bash
docker compose -f docker-compose.prod.yml pull
```

启动服务：

```bash
docker compose -f docker-compose.prod.yml up -d
```

查看状态：

```bash
docker compose -f docker-compose.prod.yml ps
```

查看日志：

```bash
docker compose -f docker-compose.prod.yml logs -f backend frontend
```

如果后端没有变为 healthy，优先查看 migration 和 readiness 日志：

```bash
docker compose -f docker-compose.prod.yml logs migrate
docker compose -f docker-compose.prod.yml logs backend
```

## 更新版本

在构建机推送新 tag 后，登录服务器修改 `.env`：

```bash
IMAGE_TAG=2026.05.13
BACKEND_IMAGE=your-dockerhub-namespace/learning-assistant-backend:2026.05.13
FRONTEND_IMAGE=your-dockerhub-namespace/learning-assistant-frontend:2026.05.13
```

然后拉取并重启：

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

`migrate` 会在每次 `up -d` 时再次尝试运行到 Alembic head；已应用的 migration 会被跳过。

## 回滚

把 `.env` 中的镜像 tag 改回上一版：

```bash
IMAGE_TAG=2026.05.12
BACKEND_IMAGE=your-dockerhub-namespace/learning-assistant-backend:2026.05.12
FRONTEND_IMAGE=your-dockerhub-namespace/learning-assistant-frontend:2026.05.12
```

重新拉取并启动：

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f backend frontend
```

注意：镜像回滚不会自动回滚数据库 schema。若某次版本包含不可逆 migration，必须按对应 release note 准备数据库回滚方案或从备份恢复。

## 外部数据库

默认 Compose 会启动内置 `postgres` 服务。若生产使用外部 PostgreSQL/PGVector：

1. 在 `.env` 中把 `DATABASE_URL` 和 `LANGGRAPH_POSTGRES_URL` 改为外部数据库地址。
2. 确认外部数据库已安装 `vector` extension，并允许应用用户执行 Alembic migration。
3. 用 Compose override 移除 `postgres` 服务和 `migrate/backend` 对 `postgres` 的 `depends_on`，或维护一份外部数据库专用 compose 文件。

后端启动时会检查 PostgreSQL、PGVector、Alembic head、必要表和索引；这些检查不通过时服务会拒绝启动。
