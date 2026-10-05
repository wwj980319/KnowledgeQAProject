# 个人知识库 AI 问答服务 MVP — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 PRD 定义的 RAG 知识库问答服务 MVP：JWT 认证 + 文档异步处理 + pgvector 检索 + Claude API 生成 + 缓存/限流，docker-compose 一键启动。

**Architecture:** FastAPI 单体 + RQ worker 双容器，PostgreSQL(pgvector) 存元数据与向量，Redis 兼任缓存/限流/队列 broker。生成回答唯一外部依赖 Claude API（`claude-sonnet-5`），向量化用本地 bge-small-zh-v1.5。

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x, pgvector, Redis, RQ, anthropic SDK, sentence-transformers, PyJWT, passlib[bcrypt], pypdf, pytest

## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）

---

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

### Task 1: 数据库层（docker 起 PG+Redis、ORM 模型、建表）

**Files:**
- Create: `docker-compose.yml`（先只含 postgres/redis）, `app/database.py`, `app/models.py`, `tests/conftest.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: `app.config.settings`
- Produces:
  - `app.database`: `engine`, `SessionLocal`, `Base`, `get_db()`（FastAPI 依赖，yield Session）, `init_db()`（建 vector 扩展 + create_all）
  - `app.models`: `User(id, email unique, password_hash, created_at)`, `Document(id, user_id FK, filename, status: str='processing', error_message nullable, created_at)`, `Chunk(id, document_id FK ondelete=CASCADE, content: Text, embedding: Vector(512), chunk_index: int)`, `QueryLog(id, user_id FK, question, answer, referenced_chunks: JSONB, created_at)`
  - `tests/conftest.py`: fixture `db`（每测试事务回滚的 Session）

- [ ] **Step 1: 写 docker-compose.yml（基础设施部分）**

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
volumes:
  pgdata:
```

- [ ] **Step 2: 启动并验证**

Run: `docker compose up -d postgres redis && sleep 8 && docker compose ps`
Expected: 两个服务 running (healthy)。失败 → 与用户人工交互。

- [ ] **Step 3: 写 app/database.py**

```python
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    from app import models  # noqa: F401  确保模型已注册
    Base.metadata.create_all(engine)
```

- [ ] **Step 4: 写 app/models.py**

```python
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    chunks = relationship("Chunk", cascade="all, delete-orphan", backref="document")


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(512))
    chunk_index: Mapped[int] = mapped_column(Integer)


class QueryLog(Base):
    __tablename__ = "query_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    referenced_chunks = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 5: 写 tests/conftest.py**

```python
import pytest
from sqlalchemy.orm import sessionmaker

from app.database import engine, init_db


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    init_db()


@pytest.fixture()
def db():
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

- [ ] **Step 6: 写失败测试 tests/test_models.py**

```python
from app.models import User


def test_create_user(db):
    user = User(email="a@b.com", password_hash="x")
    db.add(user)
    db.flush()
    assert user.id is not None
    assert user.created_at is not None
```

- [ ] **Step 7: 运行测试**

Run: `source .venv/bin/activate && pytest tests/test_models.py -v`
Expected: PASS（建表由 conftest 完成；连接失败则检查 docker compose）

---

### Task 2: 认证（注册/登录/JWT 依赖）

**Files:**
- Create: `app/schemas.py`, `app/auth.py`, `app/routers/__init__.py`, `app/routers/auth.py`, `app/main.py`, `tests/test_auth.py`
- Modify: `tests/conftest.py`（追加 client / auth_headers fixture）

**Interfaces:**
- Consumes: `get_db`, `User`, `settings`
- Produces:
  - `app.auth`: `hash_password(p: str) -> str`, `verify_password(p, hashed) -> bool`, `create_access_token(user_id: int) -> str`, `get_current_user(...) -> User`（FastAPI 依赖，Bearer token，无效返回 401）
  - `app.schemas`: `RegisterIn(email: EmailStr, password: str min_length=6)`, `LoginIn`, `TokenOut(access_token, token_type="bearer")`, `UserOut(id, email)`
  - 端点：`POST /auth/register`（201，邮箱重复 409）、`POST /auth/login`（200 TokenOut，错误 401）
  - `app.main`: `app` 实例；lifespan 时调 `init_db()`
  - conftest 追加 `client` fixture（TestClient，覆盖 get_db）和 `auth_headers` fixture（注册+登录返回 `{"Authorization": "Bearer <token>"}`）

- [ ] **Step 1: 写失败测试 tests/test_auth.py**

```python
def test_register_and_login(client):
    r = client.post("/auth/register", json={"email": "u1@t.com", "password": "secret1"})
    assert r.status_code == 201
    r2 = client.post("/auth/register", json={"email": "u1@t.com", "password": "secret1"})
    assert r2.status_code == 409
    r3 = client.post("/auth/login", json={"email": "u1@t.com", "password": "secret1"})
    assert r3.status_code == 200
    assert r3.json()["access_token"]
    r4 = client.post("/auth/login", json={"email": "u1@t.com", "password": "wrong!"})
    assert r4.status_code == 401
```

conftest.py 追加：

```python
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client):
    client.post("/auth/register", json={"email": "me@t.com", "password": "secret1"})
    token = client.post(
        "/auth/login", json={"email": "me@t.com", "password": "secret1"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

注意：TestClient 触发 lifespan 会执行 init_db()（幂等，无副作用）。

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL（`app.main` 不存在）

- [ ] **Step 3: 实现 app/auth.py**

```python
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(p: str) -> str:
    return pwd_context.hash(p)


def verify_password(p: str, hashed: str) -> bool:
    return pwd_context.verify(p, hashed)


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(401, "Missing token")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(401, "User not found")
    return user
```

- [ ] **Step 4: 实现 app/schemas.py**

```python
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
```

- [ ] **Step 5: 实现 app/routers/auth.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201, response_model=UserOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return TokenOut(access_token=create_access_token(user.id))
```

- [ ] **Step 6: 实现 app/main.py**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import auth as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Knowledge QA Service", lifespan=lifespan)
app.include_router(auth_router.router)
```

- [ ] **Step 7: 运行测试**

Run: `pytest tests/test_auth.py -v`
Expected: PASS

---

### Task 3: 分块服务

**Files:**
- Create: `app/services/__init__.py`, `app/services/chunking.py`, `tests/test_chunking.py`

**Interfaces:**
- Produces: `split_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]`（固定长度+重叠窗口；空文本返回 []；步长 = chunk_size - overlap；overlap >= chunk_size 抛 ValueError）

- [ ] **Step 1: 写失败测试 tests/test_chunking.py**

```python
from app.services.chunking import split_text


def test_empty_text():
    assert split_text("") == []


def test_short_text_single_chunk():
    assert split_text("你好世界", chunk_size=500, overlap=100) == ["你好世界"]


def test_overlap_window():
    text = "a" * 1000
    chunks = split_text(text, chunk_size=500, overlap=100)
    assert len(chunks) == 3          # 步长400: [0:500],[400:900],[800:1000]
    assert chunks[0] == text[0:500]
    assert chunks[1] == text[400:900]
    assert chunks[2] == text[800:1000]


def test_all_content_covered():
    text = "".join(str(i % 10) for i in range(1234))
    chunks = split_text(text, chunk_size=500, overlap=100)
    reconstructed = chunks[0] + "".join(c[100:] for c in chunks[1:])
    assert reconstructed == text
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_chunking.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 app/services/chunking.py**

```python
def split_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    if not text:
        return []
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    step = chunk_size - overlap
    chunks = []
    for start in range(0, len(text), step):
        chunks.append(text[start : start + chunk_size])
        if start + chunk_size >= len(text):
            break
    return chunks
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_chunking.py -v`
Expected: PASS

---

### Task 4: Embedding 服务（本地 bge-small-zh）

**Files:**
- Create: `app/services/embedding.py`, `tests/test_embedding.py`

**Interfaces:**
- Consumes: `settings.embedding_model`
- Produces: `embed_texts(texts: list[str]) -> list[list[float]]`（512 维，normalize）、`embed_query(text: str) -> list[float]`（加 bge 查询指令前缀）。模型懒加载模块级单例。

- [ ] **Step 1: 写失败测试 tests/test_embedding.py**

```python
from app.services.embedding import embed_query, embed_texts


def test_embed_texts_dimension():
    vecs = embed_texts(["缓存是什么", "限流算法"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 512


def test_embed_empty_list():
    assert embed_texts([]) == []


def test_embed_query_dimension():
    assert len(embed_query("什么是JWT")) == 512
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_embedding.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 app/services/embedding.py**

```python
from sentence_transformers import SentenceTransformer

from app.config import settings

_model: SentenceTransformer | None = None

# bge 系列：检索 query 侧加指令前缀，文档侧不加
_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return _get_model().encode(texts, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    return embed_texts([_QUERY_INSTRUCTION + text])[0]
```

- [ ] **Step 4: 运行测试（首次下载模型约 130MB）**

Run: `pytest tests/test_embedding.py -v`
Expected: PASS。下载失败（网络）→ 与用户人工交互（可配 `HF_ENDPOINT=https://hf-mirror.com` 镜像）。

---

### Task 5: 文档管理 + RQ 异步处理流水线

**Files:**
- Create: `app/services/extraction.py`, `app/tasks.py`, `app/queue.py`, `app/routers/documents.py`, `tests/test_documents.py`, `tests/test_tasks.py`
- Modify: `app/main.py`（挂 router）, `app/schemas.py`（追加 DocumentOut）

**Interfaces:**
- Consumes: `get_current_user`, `split_text`, `embed_texts`, `Document`, `Chunk`, `SessionLocal`
- Produces:
  - `app.services.extraction`: `ALLOWED_EXTENSIONS = {".txt", ".pdf"}`；`extract_text(filename: str, data: bytes) -> str`（txt utf-8 解码；pdf 用 pypdf 逐页取文本；其他 raise ValueError）
  - `app.queue`: `get_queue() -> rq.Queue`（队列名 "documents"，连接 settings.redis_url）
  - `app.tasks`: `process_document(document_id: int, text: str, filename: str) -> None`（空文本 raise → failed；分块→向量化→写 chunks→status=completed；异常 status=failed + error_message 后 re-raise 供 RQ 重试）。**设计说明**：PDF/文本提取在 API 层同步做（快、bytes 不便入 Redis），分块+向量化（慢）在 worker 做。
  - 端点：`POST /documents`（multipart file；>10MB→413；非 txt/pdf→415；提取失败→422；201 DocumentOut 并 `enqueue(..., retry=Retry(max=3))`）、`GET /documents`、`GET /documents/{id}`（他人/不存在→404）、`DELETE /documents/{id}`（204 级联删 chunks）
  - `app.schemas` 追加 `DocumentOut(id, filename, status, error_message, created_at)`

- [ ] **Step 1: 写失败测试 tests/test_documents.py**

```python
import io
from unittest.mock import patch


def _upload(client, auth_headers, name="t.txt", content=b"hello world " * 100):
    return client.post(
        "/documents",
        headers=auth_headers,
        files={"file": (name, io.BytesIO(content), "text/plain")},
    )


def test_upload_requires_auth(client):
    r = client.post("/documents", files={"file": ("t.txt", io.BytesIO(b"x"), "text/plain")})
    assert r.status_code == 401


@patch("app.routers.documents.get_queue")
def test_upload_returns_processing(mock_q, client, auth_headers):
    r = _upload(client, auth_headers)
    assert r.status_code == 201
    assert r.json()["status"] == "processing"
    assert mock_q.return_value.enqueue.called


@patch("app.routers.documents.get_queue")
def test_reject_large_file(mock_q, client, auth_headers):
    r = _upload(client, auth_headers, content=b"x" * (11 * 1024 * 1024))
    assert r.status_code == 413


@patch("app.routers.documents.get_queue")
def test_reject_unsupported_type(mock_q, client, auth_headers):
    r = _upload(client, auth_headers, name="t.docx")
    assert r.status_code == 415


@patch("app.routers.documents.get_queue")
def test_list_and_delete(mock_q, client, auth_headers):
    doc_id = _upload(client, auth_headers).json()["id"]
    listing = client.get("/documents", headers=auth_headers).json()
    assert any(d["id"] == doc_id for d in listing)
    assert client.delete(f"/documents/{doc_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/documents/{doc_id}", headers=auth_headers).status_code == 404
```

- [ ] **Step 2: 写失败测试 tests/test_tasks.py（mock embedding 避免慢）**

```python
from unittest.mock import patch

from app.models import Chunk, Document, User
from app.tasks import process_document


def _make_doc(db, email="w@t.com", filename="a.txt"):
    user = User(email=email, password_hash="x")
    db.add(user)
    db.flush()
    doc = Document(user_id=user.id, filename=filename)
    db.add(doc)
    db.flush()
    return doc


def _bind_session(db):
    # 让 task 复用测试事务中的 session；commit 降级为 flush 以便 fixture 回滚
    db.commit = db.flush
    db.close = lambda: None
    return patch("app.tasks.SessionLocal", return_value=db)


@patch("app.tasks.embed_texts", side_effect=lambda ts: [[0.0] * 512 for _ in ts])
def test_process_document_completes(mock_emb, db):
    doc = _make_doc(db)
    with _bind_session(db):
        process_document(doc.id, "测试内容。" * 200, "a.txt")
    assert doc.status == "completed"
    assert db.query(Chunk).filter_by(document_id=doc.id).count() > 0


def test_process_document_empty_text_fails(db):
    doc = _make_doc(db, email="w2@t.com", filename="bad.pdf")
    with _bind_session(db):
        try:
            process_document(doc.id, "", "bad.pdf")
        except ValueError:
            pass
    assert doc.status == "failed"
    assert doc.error_message
```

- [ ] **Step 3: 运行验证失败**

Run: `pytest tests/test_documents.py tests/test_tasks.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 app/services/extraction.py**

```python
import io

from pypdf import PdfReader

ALLOWED_EXTENSIONS = {".txt", ".pdf"}


def extract_text(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".txt"):
        return data.decode("utf-8", errors="ignore")
    if lower.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError(f"Unsupported file type: {filename}")
```

- [ ] **Step 5: 实现 app/queue.py**

```python
import redis
from rq import Queue

from app.config import settings


def get_queue() -> Queue:
    return Queue("documents", connection=redis.from_url(settings.redis_url))
```

- [ ] **Step 6: 实现 app/tasks.py**

```python
import logging

from app.database import SessionLocal
from app.models import Chunk, Document
from app.services.chunking import split_text
from app.services.embedding import embed_texts

logger = logging.getLogger(__name__)


def process_document(document_id: int, text: str, filename: str) -> None:
    db = SessionLocal()
    doc = db.get(Document, document_id)
    if doc is None:
        db.close()
        return
    try:
        if not text.strip():
            raise ValueError("empty document")
        pieces = split_text(text)
        vectors = embed_texts(pieces)
        for i, (content, vec) in enumerate(zip(pieces, vectors)):
            db.add(Chunk(document_id=document_id, content=content,
                         embedding=vec, chunk_index=i))
        doc.status = "completed"
        db.commit()
        logger.info("document processed",
                    extra={"document_id": document_id, "chunks": len(pieces)})
    except Exception as e:
        db.rollback()
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.status = "failed"
            doc.error_message = str(e)[:1000]
            db.commit()
        logger.exception("document processing failed")
        raise
    finally:
        db.close()
```

- [ ] **Step 7: 实现 app/routers/documents.py + schemas 追加 + main 挂载**

schemas.py 追加：

```python
class DocumentOut(BaseModel):
    id: int
    filename: str
    status: str
    error_message: str | None = None
    created_at: datetime
```

app/routers/documents.py：

```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from rq import Retry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Document, User
from app.queue import get_queue
from app.schemas import DocumentOut
from app.services.extraction import ALLOWED_EXTENSIONS, extract_text
from app.tasks import process_document

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", status_code=201, response_model=DocumentOut)
async def upload(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    suffix = ("." + file.filename.rsplit(".", 1)[-1].lower()) if "." in file.filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "Only .txt and .pdf are supported")
    data = await file.read()
    if len(data) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_file_size_mb}MB limit")
    try:
        text = extract_text(file.filename, data)
    except Exception:
        raise HTTPException(422, "Failed to extract text from file")
    doc = Document(user_id=user.id, filename=file.filename)
    db.add(doc)
    db.flush()
    get_queue().enqueue(process_document, doc.id, text, file.filename, retry=Retry(max=3))
    return doc


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Document).where(Document.user_id == user.id).order_by(Document.id.desc())
    return list(db.scalars(stmt))


def _get_owned(doc_id: int, user: User, db: Session) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    return _get_owned(doc_id, user, db)


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    db.delete(_get_owned(doc_id, user, db))
    db.flush()
```

main.py 追加两行（import + include_router，与 auth 同模式）：

```python
from app.routers import documents as documents_router
app.include_router(documents_router.router)
```

- [ ] **Step 8: 运行测试**

Run: `pytest tests/test_documents.py tests/test_tasks.py -v`
Expected: 全部 PASS

---

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

### Task 10: README 与面试材料

**Files:**
- Create: `README.md`, `docs/面试问答准备.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-16-knowledge-qa-design.md`（架构图、选型表、权衡）、PRD 第十二节问题清单
- Produces:
  - `README.md` 章节：项目简介 / 架构图（复用设计文档第二节 ASCII 图）/ 技术选型表（复用设计文档第一节并加"为什么"列）/ 快速开始（cp .env.example .env → 填 ANTHROPIC_API_KEY → docker compose up --build）/ API 一览表 / 关键设计权衡（全局缓存维度、固定窗口限流、pgvector 单库、本地 embedding 四条，各含"选择原因 + 局限 + 扩展方向"）
  - `docs/面试问答准备.md`：逐条回答 PRD 第十二节 6 个问题，每条按"设计思路 → 权衡 → 踩坑/扩展"结构

- [ ] **Step 1: 写 README.md**（按上述 Produces 章节结构，内容从设计文档与实际代码提取，命令须与 docker-compose.yml 实际一致）

- [ ] **Step 2: 写 docs/面试问答准备.md**（PRD 第十二节 6 问：异步队列 why / Top-K 选择与检索失败处理 / 缓存 key 设计与失效 / 限流算法权衡 / 扩展方案 / 大模型降级，每问 200-400 字）

- [ ] **Step 3: 最终验收**

Run: `pytest -v && curl -s localhost:8000/health`
Expected: 测试全绿 + health ok。对照 PRD 第十一节 DoD 8 项逐条勾选确认。
