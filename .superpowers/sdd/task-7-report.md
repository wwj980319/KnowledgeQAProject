# Task 7: RAG 问答（检索 + Claude 生成 + 降级）+ 历史记录 — Implementation Report

## Status
**DONE**

## TDD Flow
- **RED**: `pytest tests/test_rag.py tests/test_query_api.py -v` → ImportError (modules missing)
- **GREEN**: All 6 target tests pass + full suite 26/26 pass

## Files Created
1. `tests/test_rag.py` — 3 tests for RAG service (Claude mock, empty chunks, rate limit degradation)
2. `tests/test_query_api.py` — 3 tests for query endpoints (auth, POST /query, GET /query/history)
3. `app/services/rag.py` — RAG service: retrieve_chunks, generate_answer, answer_question with fallback
4. `app/routers/query.py` — Query router: POST /query, GET /query/history endpoints

## Files Modified
1. `app/schemas.py` — Appended QueryIn, SourceOut, QueryOut, QueryLogOut schemas
2. `app/main.py` — Imported and registered query_router

## Key Implementation Details

### RAG Service (`app/services/rag.py`)
- **retrieve_chunks**: Uses pgvector cosine distance with top_k limit
- **generate_answer**: Calls Claude with context chunks, returns fixed message if chunks empty, degrades gracefully on RateLimitError (503), APIStatusError (502), APIConnectionError (502)
- **answer_question**: Cache-first flow → retrieve → generate → log → cache write, returns dict with answer/sources/cached flag

### Query Router (`app/routers/query.py`)
- **POST /query**: Requires auth + rate limit check, delegates to answer_question
- **GET /query/history**: Returns latest 20 QueryLog entries for current user, ordered desc by id

### Schemas
- QueryIn: question (1-2000 chars)
- SourceOut: document_id, chunk_id, snippet (first 100 chars)
- QueryOut: answer, sources list, cached bool
- QueryLogOut: id, question, answer, referenced_chunks, created_at

## Test Summary
All target tests pass:
- test_generate_answer_calls_claude — Claude invoked with claude-sonnet-5
- test_generate_answer_empty_chunks_skips_claude — Returns fixed message without API call
- test_generate_answer_degrades_on_rate_limit — HTTPException 503 on RateLimitError
- test_query_endpoint — POST /query returns answer with auth
- test_query_requires_auth — Unauthenticated POST /query returns 401
- test_history_empty — GET /query/history returns empty list

Full suite: **26/26 pass** (no regressions)

## Concerns
None. Implementation follows brief verbatim; all constraints met:
- Claude API via anthropic SDK, model ID="claude-sonnet-5"
- All Claude calls mocked in tests
- No git operations performed
- Uses local pgvector for semantic retrieval

## Fix Report (per-user retrieval + cache isolation)

### What Changed

| File | Lines | Change |
|---|---|---|
| `app/services/cache.py` | 18-33 | `cache_key`, `get_cached_answer`, `set_cached_answer` all gain `user_id: int` as first param; key format now `qa:cache:{user_id}:<sha256>` |
| `app/services/rag.py` | 9 | Added `Document` import from `app.models` |
| `app/services/rag.py` | 26-33 | `retrieve_chunks` gains `user_id: int` as 2nd param; query now joins Document and filters `Document.user_id == user_id` |
| `app/services/rag.py` | 63-78 | `answer_question` passes `user_id` to both `get_cached_answer` and `set_cached_answer`, and to `retrieve_chunks` |
| `tests/test_cache.py` | all | Updated all call sites to new signatures; added `test_cache_key_isolated_by_user` assertion |
| `tests/test_rag.py` | added | Added `test_retrieve_chunks_isolated_by_user`: creates two users/docs/chunks, mocks embed_query, asserts retrieval returns only user A's chunk |

### Test Commands and Output

```
.venv/bin/pytest tests/test_cache.py tests/test_rag.py tests/test_query_api.py -v
# 10 passed in 0.86s

.venv/bin/pytest -q
# 29 passed, 1 warning in 5.91s
```

### Concerns
None. `app/routers/query.py` was not modified (already passes `user_id` to `answer_question`). Fix is fully contained to cache.py, rag.py, and their tests.
