from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models import Chunk, Document, User
from app.services import rag
from app.services.rag import retrieve_chunks


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


@patch("app.services.rag.embed_query", return_value=[0.0] * 512)
def test_retrieve_chunks_isolated_by_user(mock_embed, db):
    # Create two users
    user_a = User(email="user_a@test.com", password_hash="x")
    user_b = User(email="user_b@test.com", password_hash="x")
    db.add_all([user_a, user_b])
    db.flush()

    # Each user has one document
    doc_a = Document(user_id=user_a.id, filename="doc_a.txt", status="done")
    doc_b = Document(user_id=user_b.id, filename="doc_b.txt", status="done")
    db.add_all([doc_a, doc_b])
    db.flush()

    # Each document has one chunk
    chunk_a = Chunk(document_id=doc_a.id, content="chunk from A", embedding=[0.0] * 512, chunk_index=0)
    chunk_b = Chunk(document_id=doc_b.id, content="chunk from B", embedding=[0.1] * 512, chunk_index=0)
    db.add_all([chunk_a, chunk_b])
    db.flush()

    results = retrieve_chunks(db, user_a.id, "test query")

    assert len(results) >= 1
    for chunk in results:
        assert chunk.document_id == doc_a.id, (
            f"Cross-user data leak: chunk {chunk.id} belongs to doc {chunk.document_id}, "
            f"expected only doc {doc_a.id}"
        )
