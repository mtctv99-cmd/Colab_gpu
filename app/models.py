import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from app.database import Base

from sqlalchemy.orm import relationship


class WorkerAccount(Base):
    __tablename__ = "worker_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    status = Column(String, default="OFFLINE")  # OFFLINE, ACTIVE, BUSY
    last_active = Column(DateTime, nullable=True)
    gpu_info = Column(String, nullable=True)


class Voice(Base):
    __tablename__ = "voices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    audio_path = Column(String, nullable=False)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    text = Column(Text, nullable=False)
    voice_id = Column(Integer, ForeignKey("voices.id"), nullable=False)
    status = Column(
        String, default="PENDING"
    )  # PENDING, PROCESSING, COMPLETED, FAILED
    worker_email = Column(String, nullable=True)
    result_path = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    completed_at = Column(DateTime, nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
