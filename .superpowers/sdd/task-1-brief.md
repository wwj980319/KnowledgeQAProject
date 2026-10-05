## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


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

