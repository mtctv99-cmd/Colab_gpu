"""Authentication service: JWT, password hashing, API key management."""
from __future__ import annotations

import hashlib
import secrets
import os
import bcrypt
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from app.models.user import UsageRecord

_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


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
    """Count billable characters for TTS."""
    return len(text)


async def deduct_balance(user: User, characters: int, source: str, db, task_id: str | None = None) -> bool:
    """Deduct characters from user balance and record usage. Returns True if sufficient."""
    cost = characters
    if user.balance < cost:
        return False
    user.balance -= cost
    record = UsageRecord(user_id=user.id, task_id=task_id, characters=characters, cost=cost, source=source)
    db.add(record)
    return True
