from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import jwt
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from roadmind.domain.models import Role
from roadmind.infra.db import app_users, session_scope


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt_value.encode("utf-8"), 120_000
    ).hex()
    return f"pbkdf2_sha256${salt_value}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, salt, digest = password_hash.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, password_hash)


@dataclass(frozen=True)
class AppUser:
    user_id: str
    username: str
    password_hash: str
    role: Role
    region: str = "south_china"

    def public_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role.value,
            "region": self.region,
        }


SEED_USERNAMES: tuple[tuple[str, Role], ...] = (
    ("admin", Role.ADMIN),
    ("information_officer", Role.INFORMATION_OFFICER),
    ("expert", Role.EXPERT),
    ("dispatcher", Role.DISPATCHER),
    ("parts_manager", Role.PARTS_MANAGER),
    ("technician", Role.TECHNICIAN),
    ("operations", Role.OPERATIONS),
)


class UserStore(Protocol):
    def get_by_username(self, username: str) -> AppUser | None: ...

    def get_by_id(self, user_id: str) -> AppUser | None: ...

    def ensure_seed_users(self, password: str) -> None: ...


class InMemoryUserStore:
    def __init__(self) -> None:
        self._by_username: dict[str, AppUser] = {}
        self._by_id: dict[str, AppUser] = {}

    def ensure_seed_users(self, password: str) -> None:
        if self._by_username:
            return
        password_hash = hash_password(password)
        for username, role in SEED_USERNAMES:
            user = AppUser(
                user_id=f"user_{username}",
                username=username,
                password_hash=password_hash,
                role=role,
            )
            self._by_username[username] = user
            self._by_id[user.user_id] = user

    def get_by_username(self, username: str) -> AppUser | None:
        return self._by_username.get(username)

    def get_by_id(self, user_id: str) -> AppUser | None:
        return self._by_id.get(user_id)


class PostgresUserStore:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    def ensure_seed_users(self, password: str) -> None:
        password_hash = hash_password(password)
        with session_scope(self._sessions) as session:
            for username, role in SEED_USERNAMES:
                existing = session.execute(
                    select(app_users.c.user_id).where(app_users.c.username == username)
                ).first()
                if existing:
                    continue
                session.execute(
                    app_users.insert().values(
                        user_id=f"user_{username}",
                        username=username,
                        password_hash=password_hash,
                        role=role.value,
                        region="south_china",
                    )
                )

    def get_by_username(self, username: str) -> AppUser | None:
        with session_scope(self._sessions) as session:
            row = (
                session.execute(select(app_users).where(app_users.c.username == username))
                .mappings()
                .first()
            )
            return self._row_to_user(row)

    def get_by_id(self, user_id: str) -> AppUser | None:
        with session_scope(self._sessions) as session:
            row = (
                session.execute(select(app_users).where(app_users.c.user_id == user_id))
                .mappings()
                .first()
            )
            return self._row_to_user(row)

    @staticmethod
    def _row_to_user(row: Any) -> AppUser | None:
        if row is None:
            return None
        return AppUser(
            user_id=row["user_id"],
            username=row["username"],
            password_hash=row["password_hash"],
            role=Role(row["role"]),
            region=row["region"],
        )


def create_access_token(
    *,
    user: AppUser,
    secret: str,
    ttl_minutes: int,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "role": user.role.value,
        "region": user.region,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=["HS256"])
