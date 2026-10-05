import logging

import anthropic
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Chunk, Document, QueryLog
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


def retrieve_chunks(db: Session, user_id: int, question: str, top_k: int | None = None) -> list[Chunk]:
    qvec = embed_query(question)
    stmt = (
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.user_id == user_id)
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
    cached = get_cached_answer(user_id, question)
    if cached is not None:
        return {**cached, "cached": True}
    chunks = retrieve_chunks(db, user_id, question)
    answer = generate_answer(question, chunks)
    sources = [
        {"document_id": c.document_id, "chunk_id": c.id, "snippet": c.content[:100]}
        for c in chunks
    ]
    db.add(QueryLog(user_id=user_id, question=question, answer=answer,
                    referenced_chunks=sources))
    db.flush()
    payload = {"answer": answer, "sources": sources}
    set_cached_answer(user_id, question, payload)
    return {**payload, "cached": False}
