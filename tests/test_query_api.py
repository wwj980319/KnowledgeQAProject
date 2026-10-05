from unittest.mock import patch


@patch("app.routers.query.answer_question")
def test_query_endpoint(mock_answer, client, auth_headers):
    mock_answer.return_value = {"answer": "42", "sources": [], "cached": False}
    r = client.post("/query", headers=auth_headers, json={"question": "生命的意义?"})
    assert r.status_code == 200
    assert r.json()["answer"] == "42"


def test_query_requires_auth(client):
    assert client.post("/query", json={"question": "x"}).status_code == 401


@patch("app.routers.query.answer_question")
def test_history_empty(mock_answer, client, auth_headers):
    r = client.get("/query/history", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []
