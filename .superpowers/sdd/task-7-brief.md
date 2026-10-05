## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


### Task 7: RAG 问答（检索 + Claude 生成 + 降级）+ 历史记录

**Files:**
- Create: `app/services/rag.py`, `app/routers/query.py`, `tests/test_rag.py`, `tests/test_query_api.py`
- Modify: `app/main.py`（挂 router）, `app/schemas.py`（追加 QueryIn/SourceOut/QueryOut/QueryLogOut）

**Interfaces:**
- Consumes: `embed_query`, `Chunk`, `QueryLog`, cache（get/set_cached_answer）, `check_rate_limit`, `settings.claude_model / top_k / anthropic_api_key`
- Produces:
  - `app.services.rag`:
    - 模块级 `_client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)`
    - `retrieve_chunks(db, question: str, top_k: int | None = None) -> list[Chunk]`（`Chunk.embedding.cosine_distance(qvec)` 升序取 top_k）
    - `generate_answer(question: str, chunks: list[Chunk]) -> str`（chunks 为空直接返回固定话术不调 Claude；RateLimitError→HTTPException 503；APIStatusError→502；APIConnectionError→502）
    - `answer_question(db, user_id: int, question: str) -> dict`（缓存→检索→生成→落 QueryLog→写缓存；返回 `{"answer", "sources": [{"document_id","chunk_id","snippet"}], "cached"}`）
  - 端点：`POST /query`（先 check_rate_limit）、`GET /query/history`（当前用户最近 20 条）
  - schemas 追加（见 Step 4 代码）

- [ ] **Step 1: 写失败测试 tests/test_rag.py（Claude 全 mock）**

```python
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import rag


def _fake_chunk(i=1):
    return SimpleNamespace(id=i, document_id=1, content=f"片段{i}内容")


def _fake_response(text="答案"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


@patch("app.services.rag._client")
def test_generate_answer_calls_claude(mock_client):
    mock_client.messages.create.return_value = _fake_response("JWT 是……[1]")
    out = rag.generate_answer("什么是JWT", [_fake_chunk()])
    assert "JWT" in out
    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5"


def test_generate_answer_empty_chunks_skips_claude():
    out = rag.generate_answer("无关问题", [])
    assert "没有找到相关内容" in out


@patch("app.services.rag._client")
def test_generate_answer_degrades_on_rate_limit(mock_client):
    import anthropic

    mock_client.messages.create.side_effect = anthropic.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body=None,
    )
    with pytest.raises(HTTPException) as exc:
        rag.generate_answer("q", [_fake_chunk()])
    assert exc.value.status_code == 503
```

- [ ] **Step 2: 写失败测试 tests/test_query_api.py**

```python
from unittest.mock import patch


@patch("app.routers.query.answer_question")
def test_query_endpoint(mock_answer, client, auth_headers):
    mock_answer.return_value = {"answer": "42", "sources": [], "cached": False}
    r = client.post("/query", headers=auth_headers, json={"question": "生命的意义?"})
    assert r.status_code == 200
    assert r.json()["answer"] == "42"


def test_query_requires_auth(client):
    assert client.post("/query", json={"question": "x"}).status_code == 401


@patch("app.routers.query.answer_question")
def test_history_empty(mock_answer, client, auth_headers):
    r = client.get("/query/history", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 3: 运行验证失败**

Run: `pytest tests/test_rag.py tests/test_query_api.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: schemas.py 追加**

```python
class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SourceOut(BaseModel):
    document_id: int
    chunk_id: int
    snippet: str


class QueryOut(BaseModel):
    answer: str
    sources: list[SourceOut]
    cached: bool


class QueryLogOut(BaseModel):
    id: int
    question: str
    answer: str
    referenced_chunks: list
    created_at: datetime
```

- [ ] **Step 5: 实现 app/services/rag.py**

```python
import logging

import anthropic
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Chunk, QueryLog
from app.services.cache import get_cached_answer, set_cached_answer
from app.services.embedding import embed_query

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)

SYSTEM_PROMPT = (
    "你是一个知识库问答助手。只能基于用户提供的资料片段回答问题，"
    "并在句末用 [编号] 标注引用来源。若资料片段不足以回答，"
    "必须明确回答：资料中没有找到相关内容。不允许编造。"
)

NO_RESULT_ANSWER = "知识库中没有找到相关内容，请先上传相关文档或换个问法。"


def retrieve_chunks(db: Session, question: str, top_k: int | None = None) -> list[Chunk]:
    qvec = embed_query(question)
    stmt = (
        select(Chunk)
        .order_by(Chunk.embedding.cosine_distance(qvec))
        .limit(top_k or settings.top_k)
    )
    return list(db.scalars(stmt))


def generate_answer(question: str, chunks: list[Chunk]) -> str:
    if not chunks:
        return NO_RESULT_ANSWER
    context = "\n\n".join(f"[{i + 1}] {c.content}" for i, c in enumerate(chunks))
    try:
        resp = _client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"资料片段：\n{context}\n\n问题：{question}",
            }],
        )
        return next((b.text for b in resp.content if b.type == "text"), "")
    except anthropic.RateLimitError:
        logger.warning("claude rate limited")
        raise HTTPException(503, "AI 服务繁忙，请稍后再试")
    except anthropic.APIStatusError as e:
        logger.error("claude api error status=%s", e.status_code)
        raise HTTPException(502, "AI 服务暂时不可用")
    except anthropic.APIConnectionError:
        logger.error("claude connection error")
        raise HTTPException(502, "AI 服务网络异常")


def answer_question(db: Session, user_id: int, question: str) -> dict:
    cached = get_cached_answer(question)
    if cached is not None:
        return {**cached, "cached": True}
    chunks = retrieve_chunks(db, question)
    answer = generate_answer(question, chunks)
    sources = [
        {"document_id": c.document_id, "chunk_id": c.id, "snippet": c.content[:100]}
        for c in chunks
    ]
    db.add(QueryLog(user_id=user_id, question=question, answer=answer,
                    referenced_chunks=sources))
    db.flush()
    payload = {"answer": answer, "sources": sources}
    set_cached_answer(question, payload)
    return {**payload, "cached": False}
```

- [ ] **Step 6: 实现 app/routers/query.py + main 挂载**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import QueryLog, User
from app.schemas import QueryIn, QueryLogOut, QueryOut
from app.services.rag import answer_question
from app.services.rate_limit import check_rate_limit

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryOut)
def query(body: QueryIn, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    check_rate_limit(user.id)
    return answer_question(db, user.id, body.question)


@router.get("/history", response_model=list[QueryLogOut])
def history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = (select(QueryLog).where(QueryLog.user_id == user.id)
            .order_by(QueryLog.id.desc()).limit(20))
    return list(db.scalars(stmt))
```

main.py 追加：

```python
from app.routers import query as query_router
app.include_router(query_router.router)
```

- [ ] **Step 7: 运行测试**

Run: `pytest tests/test_rag.py tests/test_query_api.py -v`
Expected: PASS

---

