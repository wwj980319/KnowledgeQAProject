## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


### Task 8: 健康检查 + 结构化日志

**Files:**
- Create: `app/routers/health.py`, `app/logging_conf.py`, `tests/test_health.py`
- Modify: `app/main.py`（完整重写：挂全部 router + 请求日志中间件 + setup_logging）

**Interfaces:**
- Produces:
  - `GET /health` → `{"status": "ok"|"degraded", "postgres": bool, "redis": bool}`（任一依赖挂 → degraded，仍返回 200）
  - `app.logging_conf.setup_logging()`：JSON 行日志到 stdout
  - 请求中间件：记录 method+path / status / duration_ms

- [ ] **Step 1: 写失败测试 tests/test_health.py**

```python
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["postgres"] is True
    assert body["redis"] is True
    assert body["status"] == "ok"
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_health.py -v`
Expected: FAIL（404）

- [ ] **Step 3: 实现 app/logging_conf.py**

```python
import json
import logging
import sys


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k in ("document_id", "chunks", "user_id", "path", "status", "duration_ms"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
```

- [ ] **Step 4: 实现 app/routers/health.py**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.cache import get_redis

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    pg_ok = redis_ok = False
    try:
        db.execute(text("SELECT 1"))
        pg_ok = True
    except Exception:
        pass
    try:
        redis_ok = bool(get_redis().ping())
    except Exception:
        pass
    return {
        "status": "ok" if (pg_ok and redis_ok) else "degraded",
        "postgres": pg_ok,
        "redis": redis_ok,
    }
```

- [ ] **Step 5: 重写 app/main.py（完整文件）**

```python
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.database import init_db
from app.logging_conf import setup_logging
from app.routers import auth as auth_router
from app.routers import documents as documents_router
from app.routers import health as health_router
from app.routers import query as query_router

logger = logging.getLogger("request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    yield


app = FastAPI(title="Knowledge QA Service", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    logger.info(
        "request",
        extra={
            "path": f"{request.method} {request.url.path}",
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return response


app.include_router(auth_router.router)
app.include_router(documents_router.router)
app.include_router(query_router.router)
app.include_router(health_router.router)
```

- [ ] **Step 6: 运行全量测试**

Run: `pytest -v`
Expected: 全部 PASS

---

