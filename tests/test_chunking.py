import pytest

from app.services.chunking import split_text


def test_empty_text():
    assert split_text("") == []


def test_overlap_not_smaller_than_chunk_size_raises():
    with pytest.raises(ValueError):
        split_text("abc", chunk_size=100, overlap=100)
    with pytest.raises(ValueError):
        split_text("abc", chunk_size=100, overlap=150)


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
