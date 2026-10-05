import uuid

from app.services.cache import cache_key, get_cached_answer, set_cached_answer


def test_cache_key_normalized():
    assert cache_key(1, " 什么是JWT ") == cache_key(1, "什么是jwt")


def test_cache_roundtrip():
    q = f"roundtrip-{uuid.uuid4()}"
    assert get_cached_answer(1, q) is None
    set_cached_answer(1, q, {"answer": "42", "sources": []})
    assert get_cached_answer(1, q)["answer"] == "42"


def test_cache_key_isolated_by_user():
    assert cache_key(1, "q") != cache_key(2, "q")
