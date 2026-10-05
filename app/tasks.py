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
