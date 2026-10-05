## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


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

