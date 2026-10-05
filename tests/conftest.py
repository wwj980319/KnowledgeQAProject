import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import engine, get_db, init_db
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    init_db()


@pytest.fixture()
def db():
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client):
    client.post("/auth/register", json={"email": "me@t.com", "password": "secret1"})
    token = client.post(
        "/auth/login", json={"email": "me@t.com", "password": "secret1"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
