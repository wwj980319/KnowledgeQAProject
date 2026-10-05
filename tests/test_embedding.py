from app.services.embedding import embed_query, embed_texts


def test_embed_texts_dimension():
    vecs = embed_texts(["缓存是什么", "限流算法"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 512


def test_embed_empty_list():
    assert embed_texts([]) == []


def test_embed_query_dimension():
    assert len(embed_query("什么是JWT")) == 512
