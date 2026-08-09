from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

metadata = MetaData()

work_orders = Table(
    "work_orders",
    metadata,
    Column("service_request_id", String(64), primary_key=True),
    Column("version", Integer, nullable=False),
    Column("status", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

pii_subjects = Table(
    "pii_subjects",
    metadata,
    Column("reference", String(64), primary_key=True),
    Column("payload", JSONB, nullable=False),
)

outbox_messages = Table(
    "outbox_messages",
    metadata,
    Column("message_id", String(64), primary_key=True),
    Column("topic", String(128), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("delivered", Boolean, nullable=False, server_default=text("false")),
)

app_users = Table(
    "app_users",
    metadata,
    Column("user_id", String(64), primary_key=True),
    Column("username", String(64), unique=True, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", String(64), nullable=False),
    Column("region", String(64), nullable=False, server_default=text("'south_china'")),
)


def create_db_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def run_migrations(engine: Engine) -> None:
    metadata.create_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
