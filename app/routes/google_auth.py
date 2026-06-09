"""Google OAuth authentication."""
import httpx
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models import GoogleAccount
from app.services.auth import create_access_token
from app.routes.ws import _try_auto_rotate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

class GoogleLoginRequest(BaseModel):
    credential: str  # Google ID token
    client_id: str   # Google OAuth client ID


@router.post("/google")
async def google_login(req: GoogleLoginRequest, db: AsyncSession = Depends(get_db)):
    """Verify Google ID token, create/find user, create Colab account, start worker."""
    # Verify token with Google's tokeninfo endpoint
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": req.credential},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid Google token")

    info = resp.json()
    email = info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")

    # Check aud (audience) matches our client ID
    if info.get("aud") != req.client_id:
        raise HTTPException(status_code=401, detail="Token audience mismatch")

    # Create or find user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        # Generate random password for Google-authed users
        import secrets
        from app.services.auth import hash_password
        random_pwd = secrets.token_urlsafe(16)
        user = User(
            email=email,
            password_hash=hash_password(random_pwd),
            role="user",
            balance=50000,  # free starting balance
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("Created user from Google login: %s", email)

    # Create or find GoogleAccount for Colab worker
    result = await db.execute(select(GoogleAccount).where(GoogleAccount.email == email))
    acc = result.scalar_one_or_none()
    if not acc:
        acc = GoogleAccount(
            email=email,
            profile_name=email.split("@")[0],
            status="OFFLINE",
        )
        db.add(acc)
        await db.commit()
        logger.info("Created GoogleAccount for: %s", email)

    # Try to auto-start worker for this account
    import asyncio
    asyncio.create_task(_try_auto_rotate())

    # Generate JWT
    token = create_access_token({"user_id": user.id, "role": user.role})
    return {
        "token": token,
        "user": {"id": user.id, "email": user.email, "role": user.role, "balance": user.balance},
        "message": "Worker đang được khởi động. Vui lòng đợi 1-2 phút.",
    }
