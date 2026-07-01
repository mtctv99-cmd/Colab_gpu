"""Authentication service: JWT, password hashing, API key management."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import os
import bcrypt
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from app.models.user import UsageRecord

_jwt_secret = os.getenv("JWT_SECRET_KEY")
if not _jwt_secret:
    raise ValueError("JWT_SECRET_KEY must be set in .env")
_SECRET_KEY = _jwt_secret
_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


async def hash_password(password: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode())


async def verify_password(password: str, hashed: str) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: bcrypt.checkpw(password.encode(), hashed.encode()))


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode.update({"exp": datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES)})
    return jwt.encode(to_encode, _SECRET_KEY, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
    except JWTError:
        return None


def generate_api_key() -> tuple[str, str, str]:
    """Generate API key. Returns (plaintext_key, prefix, hashed_key)."""
    raw = secrets.token_hex(32)  # 64 hex chars
    prefix = raw[:8]
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, hashed


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def count_tts_characters(text: str) -> int:
    """Count billable characters for TTS (excludes whitespace)."""
    return len(text.replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", ""))


async def add_balance(user, amount: int, db) -> None:
    """Refund or add characters to user balance. Uses atomic UPDATE for SQLite safety."""
    from sqlalchemy import text
    from app.models.user import User

    # Atomic: no read-before-write race
    await db.execute(
        text("UPDATE users SET balance = balance + :amount WHERE id = :uid"),
        {"amount": amount, "uid": user.id}
    )
    # Reload to update caller's view
    user.balance = (await db.get(User, user.id)).balance

    record = UsageRecord(user_id=user.id, task_id=None, characters=amount, cost=-amount, source="api_refund")
    db.add(record)
    await db.commit()


async def deduct_balance(user, characters: int, source: str, db, task_id: str | None = None, type: str = "tts") -> bool:
    """Deduct characters from user balance and record usage. Returns True if sufficient. Atomic on SQLite."""
    from sqlalchemy import text
    from app.models.user import User

    if characters <= 0:
        return True

    # Atomic conditional decrement — no read-before-write race
    result = await db.execute(
        text("UPDATE users SET balance = balance - :cost WHERE id = :uid AND balance >= :cost"),
        {"cost": characters, "uid": user.id}
    )
    if result.rowcount == 0:
        return False

    # Reload to update caller's view
    user.balance = (await db.get(User, user.id)).balance

    record = UsageRecord(user_id=user.id, task_id=task_id, characters=characters, cost=characters, source=source, type=type)
    db.add(record)
    return True
