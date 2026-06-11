"""User, API key, and usage tracking models for production."""
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, BigInteger

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # "user" | "admin"
    balance = Column(BigInteger, nullable=False, default=0)  # prepaid characters
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key_prefix = Column(String(8), nullable=False)  # first 8 chars for display
    key_hash = Column(String, nullable=False)
    name = Column(String, default="Default")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    characters = Column(Integer, nullable=False)
    cost = Column(Integer, nullable=False)
    source = Column(String, nullable=False)  # "api" | "dashboard"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
