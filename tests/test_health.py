def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["postgres"] is True
    assert body["redis"] is True
    assert body["status"] == "ok"
