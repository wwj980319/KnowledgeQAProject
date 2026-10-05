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
