## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


### Task 0: 环境检查与项目骨架

**Files:**
- Create: `requirements.txt`, `.env.example`, `app/__init__.py`, `app/config.py`, `tests/__init__.py`
- Verify: Docker 可用、venv 可用

**Interfaces:**
- Produces: `app.config.settings`（pydantic-settings 单例），字段：`database_url: str`, `redis_url: str`, `anthropic_api_key: str`, `claude_model: str = "claude-sonnet-5"`, `embedding_model: str = "BAAI/bge-small-zh-v1.5"`, `jwt_secret: str`, `jwt_expire_minutes: int = 60*24`, `top_k: int = 4`, `cache_ttl_seconds: int = 3600`, `rate_limit_per_minute: int = 10`, `max_file_size_mb: int = 10`

- [ ] **Step 1: 检查环境**

Run: `docker info --format '{{.ServerVersion}}' && source /Users/wenjing/PycharmProjects/KnowledgeQAProject/.venv/bin/activate && python --version`
Expected: Docker 版本号 + `Python 3.11.x`。**任一失败 → 停止，向用户报告并等待人工处理。**

- [ ] **Step 2: 写 requirements.txt**

```
fastapi==0.116.*
uvicorn[standard]==0.35.*
sqlalchemy==2.0.*
psycopg2-binary==2.9.*
pgvector==0.4.*
redis==6.*
rq==2.*
anthropic>=0.60
sentence-transformers==5.*
pyjwt==2.*
passlib[bcrypt]==1.7.*
bcrypt==4.0.1
pypdf==5.*
pydantic-settings==2.*
python-multipart==0.0.*
pytest==8.*
httpx==0.28.*
```

- [ ] **Step 3: 安装依赖**

Run: `source .venv/bin/activate && pip install -r requirements.txt`
Expected: 全部安装成功（sentence-transformers 拉 torch 较慢属正常）。失败 → 与用户人工交互。

- [ ] **Step 4: 写 app/config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://kqa:kqa@localhost:5432/kqa"
    redis_url: str = "redis://localhost:6379/0"
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60 * 24
    top_k: int = 4
    cache_ttl_seconds: int = 3600
    rate_limit_per_minute: int = 10
    max_file_size_mb: int = 10


settings = Settings()
```

- [ ] **Step 5: 写 .env.example**

```
ANTHROPIC_API_KEY=sk-ant-xxx
DATABASE_URL=postgresql://kqa:kqa@localhost:5432/kqa
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=please-generate-a-random-secret
```

- [ ] **Step 6: 验证 config 可导入**

Run: `source .venv/bin/activate && python -c "from app.config import settings; print(settings.claude_model)"`
Expected: `claude-sonnet-5`

---

