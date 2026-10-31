from shop import auth, db


def make_connection():
    connection = db.connect(":memory:")
    db.create_schema(connection)
    return connection


def test_password_roundtrip():
    stored = auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", stored)
    assert not auth.verify_password("wrong", stored)


def test_login_returns_token():
    connection = make_connection()
    auth.register_user(connection, "a@b.com", "password123")
    token = auth.login(connection, "A@B.com", "password123")
    assert auth.get_session_user_id(token) is not None
    assert auth.login(connection, "a@b.com", "nope") is None
