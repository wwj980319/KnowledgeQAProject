## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


### Task 6: 缓存 + 限流

**Files:**
- Create: `app/services/cache.py`, `app/services/rate_limit.py`, `tests/test_cache.py`, `tests/test_rate_limit.py`

**Interfaces:**
- Consumes: `settings.redis_url / cache_ttl_seconds / rate_limit_per_minute`
- Produces:
  - `app.services.cache`: `get_redis() -> redis.Redis`（模块级单例，decode_responses=True）、`cache_key(question: str) -> str`（strip+lower → sha256，形如 `qa:cache:<hex>`）、`get_cached_answer(question) -> dict | None`、`set_cached_answer(question, payload: dict) -> None`（JSON，TTL）
  - `app.services.rate_limit`: `check_rate_limit(user_id: int) -> None`（固定窗口 `rl:{user_id}:{epoch//60}`，INCR + 首次 EXPIRE 60；超限抛 HTTPException 429）

- [ ] **Step 1: 写失败测试**

tests/test_cache.py：

```python
import uuid

from app.services.cache import cache_key, get_cached_answer, set_cached_answer


def test_cache_key_normalized():
    assert cache_key(" 什么是JWT ") == cache_key("什么是jwt")


def test_cache_roundtrip():
    q = f"roundtrip-{uuid.uuid4()}"
    assert get_cached_answer(q) is None
    set_cached_answer(q, {"answer": "42", "sources": []})
    assert get_cached_answer(q)["answer"] == "42"
```

tests/test_rate_limit.py：

```python
import random

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services.rate_limit import check_rate_limit


def test_rate_limit_blocks_after_threshold():
    user_id = random.randint(10**8, 10**9)  # 随机 id 防跨测试污染
    for _ in range(settings.rate_limit_per_minute):
        check_rate_limit(user_id)
    with pytest.raises(HTTPException) as exc:
        check_rate_limit(user_id)
    assert exc.value.status_code == 429
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_cache.py tests/test_rate_limit.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 app/services/cache.py**

```python
import hashlib
import json

import redis

from app.config import settings

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def cache_key(question: str) -> str:
    normalized = question.strip().lower()
    return "qa:cache:" + hashlib.sha256(normalized.encode()).hexdigest()


def get_cached_answer(question: str) -> dict | None:
    raw = get_redis().get(cache_key(question))
    return json.loads(raw) if raw else None


def set_cached_answer(question: str, payload: dict) -> None:
    get_redis().set(
        cache_key(question),
        json.dumps(payload, ensure_ascii=False),
        ex=settings.cache_ttl_seconds,
    )
```

- [ ] **Step 4: 实现 app/services/rate_limit.py**

```python
import time

from fastapi import HTTPException

from app.config import settings
from app.services.cache import get_redis


def check_rate_limit(user_id: int) -> None:
    window = int(time.time()) // 60
    key = f"rl:{user_id}:{window}"
    r = get_redis()
    count = r.incr(key)
    if count == 1:
        r.expire(key, 60)
    if count > settings.rate_limit_per_minute:
        raise HTTPException(429, "Rate limit exceeded, try again later")
```

- [ ] **Step 5: 运行测试**

Run: `pytest tests/test_cache.py tests/test_rate_limit.py -v`
Expected: PASS

---

