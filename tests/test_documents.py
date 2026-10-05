import io
from unittest.mock import patch


def _upload(client, auth_headers, name="t.txt", content=b"hello world " * 100):
    return client.post(
        "/documents",
        headers=auth_headers,
        files={"file": (name, io.BytesIO(content), "text/plain")},
    )


def test_upload_requires_auth(client):
    r = client.post("/documents", files={"file": ("t.txt", io.BytesIO(b"x"), "text/plain")})
    assert r.status_code == 401


@patch("app.routers.documents.get_queue")
def test_upload_returns_processing(mock_q, client, auth_headers):
    r = _upload(client, auth_headers)
    assert r.status_code == 201
    assert r.json()["status"] == "processing"
    assert mock_q.return_value.enqueue.called


@patch("app.routers.documents.get_queue")
def test_reject_large_file(mock_q, client, auth_headers):
    r = _upload(client, auth_headers, content=b"x" * (11 * 1024 * 1024))
    assert r.status_code == 413


@patch("app.routers.documents.get_queue")
def test_reject_unsupported_type(mock_q, client, auth_headers):
    r = _upload(client, auth_headers, name="t.docx")
    assert r.status_code == 415


@patch("app.routers.documents.get_queue")
def test_list_and_delete(mock_q, client, auth_headers):
    doc_id = _upload(client, auth_headers).json()["id"]
    listing = client.get("/documents", headers=auth_headers).json()
    assert any(d["id"] == doc_id for d in listing)
    assert client.delete(f"/documents/{doc_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/documents/{doc_id}", headers=auth_headers).status_code == 404
