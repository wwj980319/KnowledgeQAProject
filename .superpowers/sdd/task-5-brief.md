## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


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

