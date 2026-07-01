"""SQLAlchemy ORM models for the application."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class GoogleAccount(Base):
    __tablename__ = "google_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    profile_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="READY")
    last_active = Column(DateTime, nullable=True)
    quota_reset_at = Column(DateTime, nullable=True)
    colab_pid = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)

    worker_session_id = Column(String, nullable=True)
    runtime_status = Column(String, nullable=True)
    current_task_id = Column(String, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    idle_since = Column(DateTime, nullable=True)
    assigned_node_id = Column(String, nullable=True)
    colab_notebook_url = Column(String, nullable=True)

    tasks = relationship("Task", back_populates="worker")


class WorkerSession(Base):
    __tablename__ = "worker_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, nullable=False)
    worker_session_id = Column(String, unique=True, nullable=False)
    colab_endpoint = Column(String, nullable=True)
    colab_token = Column(String, nullable=True)
    session_name = Column(String, nullable=True)
    kernel_id = Column(String, nullable=True)
    keep_alive_pid = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_alive_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="STARTING")


class Voice(Base):
    __tablename__ = "voices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    audio_path = Column(String, nullable=False)
    transcript = Column(Text, nullable=True)

    tasks = relationship("Task", back_populates="voice", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    text = Column(Text, nullable=False)
    voice_id = Column(Integer, ForeignKey("voices.id"), nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    worker_id = Column(Integer, ForeignKey("google_accounts.id"), nullable=True)
    result_audio_path = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    language = Column(String, nullable=True, default=None)
    batch_id = Column(String, nullable=True, default=None)
    webhook_url = Column(String, nullable=True, default=None)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    worker_session_id = Column(String, nullable=True)
    attempt = Column(Integer, nullable=False, default=0)
    leased_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)

    voice = relationship("Voice", back_populates="tasks")
    worker = relationship("GoogleAccount", back_populates="tasks")

from app.models.user import User, ApiKey, UsageRecord
