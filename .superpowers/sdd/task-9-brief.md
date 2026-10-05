## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


### Task 9: Docker 化（api + worker 容器）

**Files:**
- Create: `Dockerfile`, `.dockerignore`
- Modify: `docker-compose.yml`（追加 api / worker）

**Interfaces:**
- Produces: `docker compose up --build -d` 一键起四服务；worker 命令 `rq worker documents --url redis://redis:6379/0`；HF 模型缓存 volume `hf_cache:/root/.cache/huggingface`

- [ ] **Step 1: 写 Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 写 .dockerignore**

```
.venv
.idea
docs
tests
__pycache__
*.pyc
.env
```

- [ ] **Step 3: docker-compose.yml 完整文件（追加 api/worker）**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: kqa
      POSTGRES_PASSWORD: kqa
      POSTGRES_DB: kqa
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U kqa"]
      interval: 5s
      retries: 10
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  api:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql://kqa:kqa@postgres:5432/kqa
      REDIS_URL: redis://redis:6379/0
    ports: ["8000:8000"]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_started}
    volumes: [hf_cache:/root/.cache/huggingface]
  worker:
    build: .
    command: rq worker documents --url redis://redis:6379/0
    env_file: .env
    environment:
      DATABASE_URL: postgresql://kqa:kqa@postgres:5432/kqa
      REDIS_URL: redis://redis:6379/0
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_started}
    volumes: [hf_cache:/root/.cache/huggingface]
volumes:
  pgdata:
  hf_cache:
```

- [ ] **Step 4: 构建并启动**

Run: `docker compose up --build -d && sleep 20 && curl -s localhost:8000/health`
Expected: `{"status":"ok","postgres":true,"redis":true}`。失败 → `docker compose logs api` 排查并与用户交互。

- [ ] **Step 5: 端到端冒烟（真实 Claude 调用，需 .env 有效 key；与用户确认后执行）**

Run:
```bash
curl -s -X POST localhost:8000/auth/register -H 'content-type: application/json' \
  -d '{"email":"demo@t.com","password":"secret1"}'
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"email":"demo@t.com","password":"secret1"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "FastAPI 是一个现代 Python Web 框架，基于类型注解提供自动交互文档。" > /tmp/demo.txt
curl -s -X POST localhost:8000/documents -H "Authorization: Bearer $TOKEN" -F "file=@/tmp/demo.txt"
sleep 20   # 等 worker 处理（首次含模型下载会更久，可看 docker compose logs worker）
curl -s -X POST localhost:8000/query -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"question":"FastAPI 是什么？"}'
```
Expected: 返回基于文档内容的回答且 sources 非空；重复同一问题第二次 `cached: true` 且明显更快。

---

