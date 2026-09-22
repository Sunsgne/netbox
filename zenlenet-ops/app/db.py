"""SQLite session and first-run seed."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.content import DEFAULT_PRICES, NOTICE_TEMPLATES


class Base(DeclarativeBase):
    pass


def database_path() -> Path:
    raw = os.environ.get("DATABASE_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "data" / "zenlenet.db"


def _build_engine():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password, salt).split("$", 1)[1]
    return hmac.compare_digest(candidate, digest)


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        _seed_user(session)
        _seed_prices(session)
        _seed_templates(session)
        session.commit()


def _seed_user(session) -> None:
    from app.models import User

    if session.scalar(select(User).limit(1)):
        return
    username = os.environ.get("ADMIN_USER", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "zenlenet-demo")
    session.add(User(username=username, password_hash=hash_password(password)))


def _seed_prices(session) -> None:
    from app.models import Price

    existing = {row.code for row in session.scalars(select(Price))}
    for code, name, amount in DEFAULT_PRICES:
        if code not in existing:
            session.add(Price(code=code, name=name, amount=amount))


def _seed_templates(session) -> None:
    from app.models import NoticeTemplate

    existing = {row.code for row in session.scalars(select(NoticeTemplate))}
    for code, name, scene, subject, body in NOTICE_TEMPLATES:
        if code not in existing:
            session.add(NoticeTemplate(code=code, name=name, scene=scene, subject=subject, body=body))


def price_map(session) -> dict[str, float]:
    from app.models import Price

    return {row.code: row.amount for row in session.scalars(select(Price))}
