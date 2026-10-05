def test_register_and_login(client):
    r = client.post("/auth/register", json={"email": "u1@t.com", "password": "secret1"})
    assert r.status_code == 201
    r2 = client.post("/auth/register", json={"email": "u1@t.com", "password": "secret1"})
    assert r2.status_code == 409
    r3 = client.post("/auth/login", json={"email": "u1@t.com", "password": "secret1"})
    assert r3.status_code == 200
    assert r3.json()["access_token"]
    r4 = client.post("/auth/login", json={"email": "u1@t.com", "password": "wrong!"})
    assert r4.status_code == 401
