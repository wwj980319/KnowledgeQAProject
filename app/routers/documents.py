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
