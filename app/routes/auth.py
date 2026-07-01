"""Authentication and user management routes."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Task
from app.models.user import User, ApiKey, UsageRecord
from app.services.auth import hash_password, verify_password, create_access_token, decode_access_token, generate_api_key, hash_api_key, count_tts_characters
from sqlalchemy import func

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
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
        # Check expiry
        if ak.expires_at:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            expires_at = ak.expires_at
            if expires_at.tzinfo is not None:
                now_compare = now
            else:
                now_compare = now.replace(tzinfo=None)
            if now_compare > expires_at:
                return None

        # Check allowed IPs — use client.host (not X-Forwarded-For) to prevent spoofing
        if ak.allowed_ips and request:
            try:
                import json
                allowed = json.loads(ak.allowed_ips)
                if isinstance(allowed, list) and len(allowed) > 0:
                    ip = request.client.host if request.client else "unknown"
                    if ip not in allowed:
                        return None
            except Exception:
                pass

        # Update last_used_at but only write DB every 5 min to reduce SQLite write pressure
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        from app.routes.auth import _last_used_cache
        last = _last_used_cache.get(ak.id)
        if not last or (now - last).total_seconds() > 300:
            ak.last_used_at = now
            _last_used_cache[ak.id] = now
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
@router.post("/register")
async def signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    _check_login_rate(req.email)  # rate limit signups too
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if not req.email or "@" not in req.email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(email=req.email, password_hash=await hash_password(req.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"user_id": user.id, "role": user.role})
    return {"token": token, "user": {"id": user.id, "email": user.email, "role": user.role, "balance": user.balance, "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None}}


# ── Brute force protection ────────────────────────────────────
_login_attempts: dict[str, list[float]] = {}  # email -> timestamps
_login_attempts_ip: dict[str, list[float]] = {}  # ip -> timestamps
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300  # 5 minutes
_last_login_cleanup: float = 0.0
_last_used_cache: dict[int, 'datetime'] = {}  # api_key id -> last written timestamp


def _check_login_rate(email: str):
    import time
    now = time.time()
    # Periodic cleanup: remove stale email keys with empty lists
    global _last_login_cleanup
    if now - _last_login_cleanup > 600.0:
        _last_login_cleanup = now
        empty = [k for k, v in _login_attempts.items() if not v]
        for k in empty:
            del _login_attempts[k]
        empty_ip = [k for k, v in _login_attempts_ip.items() if not v]
        for k in empty_ip:
            del _login_attempts_ip[k]

    attempts = _login_attempts.get(email, [])
    attempts = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        logger.warning("Brute force attempt detected for %s (%d failures)", email, len(attempts))
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 5 minutes.")
    attempts.append(now)
    _login_attempts[email] = attempts


def _clear_login_rate(email: str):
    _login_attempts.pop(email, None)


# ── Login ──────────────────────────────────────────────────────
@router.post("/login")
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _check_login_rate(req.email)
    # Per-IP rate limiting
    import time as _time
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    ip_attempts = _login_attempts_ip.get(ip, [])
    ip_attempts = [t for t in ip_attempts if now - t < _LOGIN_WINDOW_SECONDS]
    if len(ip_attempts) >= _LOGIN_MAX_ATTEMPTS * 3:
        raise HTTPException(status_code=429, detail="Too many login attempts from this IP.")
    ip_attempts.append(now)
    _login_attempts_ip[ip] = ip_attempts
    result = await db.execute(select(User).where(User.email == req.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not await verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _clear_login_rate(req.email)
    user.last_login_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    await db.commit()

    token = create_access_token({"user_id": user.id, "role": user.role})

    remaining = max(0, _LOGIN_MAX_ATTEMPTS - len(_login_attempts.get(req.email, [])))
    return JSONResponse(
        content={"token": token, "user": {"id": user.id, "email": user.email, "role": user.role, "balance": user.balance, "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None}},
        headers={"X-RateLimit-Remaining": str(remaining)},
    )


# ── Change password ───────────────────────────────────────────
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    if not await verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    user.password_hash = await hash_password(req.new_password)
    await db.commit()
    return {"detail": "Password updated"}

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

@router.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalars().first()
    if user:
        pass
    return {"detail": "If the email exists, a reset link has been sent."}

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    # Stub: decoding token logic to get user...
    raise HTTPException(status_code=400, detail="Invalid token")


# ── Profile ────────────────────────────────────────────────────
@router.get("/profile")
async def get_profile(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)):
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "balance": user.balance,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
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


# ── Admin: create user ─────────────────────────────────────────
class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str = "user"

@router.post("/admin/users")
async def admin_create_user(req: CreateUserRequest, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=req.email, password_hash=await hash_password(req.password), role=req.role)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "email": user.email, "role": user.role, "balance": user.balance}


# ── Admin: delete user ─────────────────────────────────────────
@router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Delete related records first to avoid FK constraint failure
    from app.models.user import ApiKey, UsageRecord
    from sqlalchemy import delete, update
    await db.execute(delete(ApiKey).where(ApiKey.user_id == user_id))
    await db.execute(delete(UsageRecord).where(UsageRecord.user_id == user_id))
    await db.execute(
        update(Task).where(Task.user_id == user_id).values(user_id=None)
    )
    await db.delete(user)
    await db.commit()
    return {"detail": "Deleted"}


# ── Admin: update user ─────────────────────────────────────────
class UpdateUserRequest(BaseModel):
    balance: int | None = None
    role: str | None = None
    is_active: bool | None = None

@router.put("/admin/users/{user_id}")
async def admin_update_user(user_id: int, req: UpdateUserRequest, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.balance is not None:
        user.balance = req.balance
    if req.role is not None:
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active
    await db.commit()
    return {"id": user.id, "email": user.email, "role": user.role, "balance": user.balance, "is_active": user.is_active}


# ── Admin: list all API keys ────────────────────────────────────
@router.get("/admin/api-keys")
async def admin_list_api_keys(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiKey, User.email).join(User, ApiKey.user_id == User.id).order_by(ApiKey.created_at.desc())
    )
    return [
        {
            "id": k.ApiKey.id,
            "key_prefix": k.ApiKey.key_prefix,
            "name": k.ApiKey.name,
            "is_active": k.ApiKey.is_active,
            "user_id": k.ApiKey.user_id,
            "user_email": k.email,
            "created_at": k.ApiKey.created_at.isoformat() if k.ApiKey.created_at else None,
            "last_used_at": k.ApiKey.last_used_at.isoformat() if k.ApiKey.last_used_at else None,
            "expires_at": k.ApiKey.expires_at.isoformat() if k.ApiKey.expires_at else None,
            "rate_limit": k.ApiKey.rate_limit,
            "allowed_ips": k.ApiKey.allowed_ips,
            "notes": k.ApiKey.notes,
        }
        for k in result.all()
    ]


# ── Admin: create API key for any user ─────────────────────────
class AdminCreateApiKeyRequest(BaseModel):
    user_id: int
    name: str = "Default"

@router.post("/admin/api-keys")
async def admin_create_api_key(req: AdminCreateApiKeyRequest, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, req.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    raw, prefix, hashed = generate_api_key()
    ak = ApiKey(user_id=req.user_id, key_prefix=prefix, key_hash=hashed, name=req.name)
    db.add(ak)
    await db.commit()
    return {"key": raw, "key_prefix": prefix, "name": req.name, "user_email": user.email, "message": "Save the key now — it won't be shown again"}



class AdminUpdateApiKeyRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    expires_at: str | None = None
    rate_limit: int | None = None
    allowed_ips: list[str] | None = None
    notes: str | None = None

@router.patch("/admin/api-keys/{key_id}")
async def admin_update_api_key(key_id: int, req: AdminUpdateApiKeyRequest, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Update API key settings: name, active status, expiry, rate limit, allowed IPs, notes."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    ak = result.scalar_one_or_none()
    if not ak:
        raise HTTPException(status_code=404, detail="API key not found")
    if req.name is not None:
        ak.name = req.name
    if req.is_active is not None:
        ak.is_active = req.is_active
    if req.expires_at is not None:
        ak.expires_at = datetime.fromisoformat(req.expires_at) if isinstance(req.expires_at, str) else req.expires_at
    if req.rate_limit is not None:
        ak.rate_limit = req.rate_limit
    if req.allowed_ips is not None:
        import json as _json
        ak.allowed_ips = _json.dumps(req.allowed_ips)
    if req.notes is not None:
        ak.notes = req.notes
    await db.commit()
    return {"detail": "Updated"}

@router.get("/admin/api-keys/{key_id}/usage")
async def admin_api_key_usage(key_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Get usage stats for a specific API key (via user_id)."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    ak = result.scalar_one_or_none()
    if not ak:
        raise HTTPException(status_code=404, detail="API key not found")
    from sqlalchemy import func as _func
    result = await db.execute(
        select(
            _func.count(UsageRecord.id).label("total_requests"),
            _func.coalesce(_func.sum(UsageRecord.characters), 0).label("total_characters"),
        ).where(UsageRecord.user_id == ak.user_id)
    )
    row = result.one()
    return {
        "total_requests": row.total_requests,
        "total_characters": row.total_characters,
        "user_id": ak.user_id,
    }

# ── Admin: hard delete API key ──────────────────────────────────
@router.delete("/admin/api-keys/{key_id}")
async def admin_delete_api_key(key_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    ak = result.scalar_one_or_none()
    if not ak:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(ak)
    await db.commit()
    return {"detail": "Deleted"}





# ── Colab OAuth flow ──────────────────────────────────────────
import json as _json
import os as _os
from google_auth_oauthlib.flow import InstalledAppFlow as _InstalledAppFlow

_COLAB_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/colaboratory",
    "https://www.googleapis.com/auth/drive.file",
]
_COLAB_REDIRECT = "https://sdk.cloud.google.com/applicationdefaultauthcode.html"

def _load_colab_client_config() -> dict:
    """Load OAuth client config from bundled file or home directory."""
    paths = [
        _os.path.expanduser("~/.colab-cli-oauth-config.json"),
        _os.path.join(_os.path.dirname(__file__), "..", "colab_cli", "oauth_config.json"),
    ]
    for p in paths:
        p = _os.path.abspath(p)
        if _os.path.exists(p):
            with open(p) as f:
                return _json.load(f)
    # Fallback: embedded minimal config
    raise RuntimeError("OAuth config not found. Check app/colab_cli/oauth_config.json")

class ColabAuthUrlRequest(BaseModel):
    email: str

@router.post("/colab/auth-url")
async def colab_auth_url(req: ColabAuthUrlRequest, admin: User = Depends(require_admin)):
    email = req.email
    """Generate Colab OAuth URL for a given email. Admin only."""
    client_config = _load_colab_client_config()
    flow = _InstalledAppFlow.from_client_config(client_config, _COLAB_SCOPES)
    flow.redirect_uri = _COLAB_REDIRECT
    auth_url, _ = flow.authorization_url(prompt="consent", token_usage="remote",
                                          access_type="offline", include_granted_scopes="true")
    # Store flow state temporarily for callback
    _save_flow(email, flow)
    return {"auth_url": auth_url, "email": email, "message": "Open URL in browser, authorize, then POST /api/auth/colab/callback with the code."}

_PENDING_FLOW_DIR = _os.path.expanduser("~/.config/colab-cli/flows")
_os.makedirs(_PENDING_FLOW_DIR, exist_ok=True)

def _cleanup_stale_flows(max_age: int = 1800) -> None:
    """Remove flow files older than max_age seconds (default 30 min)."""
    now = __import__("time").time()
    try:
        for fn in _os.listdir(_PENDING_FLOW_DIR):
            fp = _os.path.join(_PENDING_FLOW_DIR, fn)
            if _os.path.isfile(fp) and now - _os.path.getmtime(fp) > max_age:
                _os.remove(fp)
    except Exception:
        pass

# Run cleanup on import
_cleanup_stale_flows()

def _save_flow(email: str, flow: object) -> None:
    """Persist OAuth flow state as JSON so it survives server restart."""
    try:
        safe = email.replace("@", "_at_").replace(".", "_")
        data = {
            "client_config": flow.client_config,
            "redirect_uri": flow.redirect_uri,
            "code_verifier": flow.code_verifier,
            "scopes": flow.oauth2session.scope,
        }
        with open(_os.path.join(_PENDING_FLOW_DIR, f"{safe}.json"), "w") as f:
            _json.dump(data, f)
    except Exception:
        pass

def _load_flow(email: str) -> object | None:
    """Load persisted OAuth flow state from JSON and reconstruct the flow."""
    try:
        safe = email.replace("@", "_at_").replace(".", "_")
        path = _os.path.join(_PENDING_FLOW_DIR, f"{safe}.json")
        if _os.path.exists(path):
            with open(path) as f:
                data = _json.load(f)
            # Reconstruct InstalledAppFlow from saved params
            scopes = data["scopes"]
            if isinstance(scopes, str):
                scopes = scopes.split()
            from google_auth_oauthlib.flow import InstalledAppFlow as _InstalledAppFlow
            flow = _InstalledAppFlow.from_client_config(
                {"installed": data["client_config"]}, scopes
            )
            flow.redirect_uri = data["redirect_uri"]
            flow.code_verifier = data["code_verifier"]
            return flow
    except Exception:
        pass
    return None

def _clear_flow(email: str) -> None:
    """Remove persisted flow state."""
    try:
        safe = email.replace("@", "_at_").replace(".", "_")
        path = _os.path.join(_PENDING_FLOW_DIR, f"{safe}.json")
        if _os.path.exists(path):
            _os.remove(path)
    except Exception:
        pass

class ColabCallbackRequest(BaseModel):
    email: str
    code: str

@router.post("/colab/callback")
async def colab_callback(req: ColabCallbackRequest, admin: User = Depends(require_admin)):
    """Accept OAuth authorization code and save token for the email."""
    flow = _load_flow(req.email)
    if not flow:
        raise HTTPException(status_code=400, detail="No pending auth flow. Call /api/auth/colab/auth-url first, and don't restart server in between.")
    try:
        flow.fetch_token(code=req.code)
        creds = flow.credentials
        safe = req.email.replace("@", "_at_").replace(".", "_")
        token_dir = _os.path.expanduser("~/.config/colab-cli")
        _os.makedirs(token_dir, exist_ok=True)
        token_path = _os.path.join(token_dir, f"token_{safe}.json")
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        # Update DB
        from app.database import async_session
        from sqlalchemy import update
        from app.models import GoogleAccount
        async with async_session() as db:
            await db.execute(
                update(GoogleAccount)
                .where(GoogleAccount.email == req.email)
                .values(status="READY", runtime_status=None, worker_session_id=None)
            )
            await db.commit()
        _clear_flow(req.email)
        return {"status": "ok", "email": req.email, "message": "Token saved. Account is READY."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Code exchange failed: {e}")
