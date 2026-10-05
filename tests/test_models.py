from app.models import User


def test_create_user(db):
    user = User(email="a@b.com", password_hash="x")
    db.add(user)
    db.flush()
    assert user.id is not None
    assert user.created_at is not None
