from __future__ import annotations

from roadmind.auth.users import (
    InMemoryUserStore,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("roadmind123")
    assert verify_password("roadmind123", hashed)
    assert not verify_password("wrong", hashed)


def test_seed_users_and_jwt():
    store = InMemoryUserStore()
    store.ensure_seed_users("roadmind123")
    user = store.get_by_username("dispatcher")
    assert user is not None
    assert user.role.value == "dispatcher"
    token = create_access_token(
        user=user, secret="unit-test-secret-32-characters!!", ttl_minutes=30
    )
    payload = decode_access_token(token, secret="unit-test-secret-32-characters!!")
    assert payload["sub"] == user.user_id
    assert payload["role"] == "dispatcher"
