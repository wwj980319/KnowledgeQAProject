## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


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

