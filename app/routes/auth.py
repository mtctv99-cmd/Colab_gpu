"""Authentication and user management routes."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, ApiKey, UsageRecord
from app.services.auth import hash_password, verify_password, create_access_token, decode_access_token, generate_api_key, hash_api_key, count_tts_characters
from sqlalchemy import func

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Extract user from JWT or API key. Returns None if unauthenticated."""
    token = None
    if credentials:
        token = credentials.credentials
    elif authorization and authorization.startswith("Bearer "):
        token = authorization[7:]

    if not token:
        return None

    # Try JWT first
    payload = decode_access_token(token)
    if payload and "user_id" in payload:
        result = await db.execute(select(User).where(User.id == payload["user_id"], User.is_active == True))
        return result.scalar_one_or_none()

    # Try API key
    hashed = hash_api_key(token)
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == hashed, ApiKey.is_active == True))
    ak = result.scalar_one_or_none()
    if ak:
        ak.last_used_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        await db.commit()
        result = await db.execute(select(User).where(User.id == ak.user_id, User.is_active == True))
        return result.scalar_one_or_none()

    return None


async def require_user(user: User | None = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Request / Response models ──────────────────────────────────

class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class CreateApiKeyRequest(BaseModel):
    name: str = "Default"

class AdminTopupRequest(BaseModel):
    email: str
    amount: int


# ── Signup ─────────────────────────────────────────────────────
@router.post("/signup")
async def signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(email=req.email, password_hash=hash_password(req.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"user_id": user.id, "role": user.role})
    return {"token": token, "user": {"id": user.id, "email": user.email, "role": user.role, "balance": user.balance}}


# ── Login ──────────────────────────────────────────────────────
@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({"user_id": user.id, "role": user.role})
    return {"token": token, "user": {"id": user.id, "email": user.email, "role": user.role, "balance": user.balance}}


# ── Profile ────────────────────────────────────────────────────
@router.get("/profile")
async def get_profile(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "balance": user.balance,
    }


# ── API Key management ─────────────────────────────────────────
@router.get("/api-keys")
async def list_api_keys(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    return [
        {"id": k.id, "key_prefix": k.key_prefix, "name": k.name, "is_active": k.is_active, "created_at": k.created_at.isoformat() if k.created_at else None, "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}
        for k in result.scalars().all()
    ]

@router.post("/api-keys")
async def create_api_key(req: CreateApiKeyRequest, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    raw, prefix, hashed = generate_api_key()
    ak = ApiKey(user_id=user.id, key_prefix=prefix, key_hash=hashed, name=req.name)
    db.add(ak)
    await db.commit()
    return {"key": raw, "key_prefix": prefix, "name": req.name, "message": "Save the key now — it won't be shown again"}

@router.delete("/api-keys/{key_id}")
async def delete_api_key(key_id: int, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    ak = result.scalar_one_or_none()
    if not ak:
        raise HTTPException(status_code=404, detail="API key not found")
    ak.is_active = False
    await db.commit()
    return {"detail": "Deactivated"}


# ── Admin: list users ─────────────────────────────────────────
@router.get("/admin/users")
async def admin_list_users(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [
        {"id": u.id, "email": u.email, "role": u.role, "balance": u.balance, "is_active": u.is_active, "created_at": u.created_at.isoformat() if u.created_at else None}
        for u in result.scalars().all()
    ]


# ── Admin: top-up balance ──────────────────────────────────────
@router.post("/admin/topup")
async def admin_topup(req: AdminTopupRequest, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.balance += req.amount
    await db.commit()
    await db.refresh(user)
    return {"email": user.email, "new_balance": user.balance, "added": req.amount}


# ── Webhook: auto top-up (payment callback) ────────────────────
class WebhookTopupRequest(BaseModel):
    email: str
    amount: int
    secret: str = ""

@router.post("/webhook/topup")
async def webhook_topup(req: WebhookTopupRequest, db: AsyncSession = Depends(get_db)):
    import os
    webhook_secret = os.getenv("WEBHOOK_SECRET", "")
    if webhook_secret and req.secret != webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid secret")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.balance += req.amount
    await db.commit()
    await db.refresh(user)
    return {"email": user.email, "new_balance": user.balance, "added": req.amount}


# ── Usage history ──────────────────────────────────────────────
@router.get("/usage")
async def get_usage(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UsageRecord).where(UsageRecord.user_id == user.id).order_by(UsageRecord.created_at.desc()).limit(50))
    total_result = await db.execute(select(func.coalesce(func.sum(UsageRecord.cost), 0)).where(UsageRecord.user_id == user.id))
    total_used = total_result.scalar() or 0
    return {
        "balance": user.balance,
        "total_used": total_used,
        "records": [
            {
                "id": r.id,
                "characters": r.characters,
                "cost": r.cost,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in result.scalars().all()
        ],
    }
