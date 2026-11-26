import time
from collections import defaultdict
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    hash_password,
    require_admin,
    verify_password,
)
from app.models.entities import AdminAccount

router = APIRouter(prefix="/auth", tags=["Admin Authentication"])

_ALLOWED_ALIASES = {"admin", "rais", "rais.frozenfoods@gmail.com"}
_FAILED_ATTEMPTS: Dict[str, Dict[str, float]] = defaultdict(lambda: {"count": 0, "locked_until": 0.0})
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    passkey: str = Field(..., min_length=1, max_length=200)


class ChangePasskeyRequest(BaseModel):
    current_passkey: str = Field(..., min_length=1, max_length=200)
    new_passkey: str = Field(..., min_length=6, max_length=200)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    host = request.client.host if request.client else "unknown"
    return forwarded or host


@router.post("/login")
async def login_admin(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticates admin credentials server-side against Neon Postgres bcrypt hash and returns a Bearer JWT."""
    key = _client_key(request)
    now = time.time()
    rec = _FAILED_ATTEMPTS[key]
    if rec["locked_until"] > now:
        wait_s = max(1, int(rec["locked_until"] - now))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {wait_s}s.",
        )

    clean_user = payload.username.strip().lower()
    if clean_user not in _ALLOWED_ALIASES:
        rec["count"] += 1
        if rec["count"] >= _MAX_ATTEMPTS:
            rec["locked_until"] = now + _LOCKOUT_SECONDS
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin username or passkey.",
        )

    acc = (
        await db.execute(select(AdminAccount).where(AdminAccount.username == "admin"))
    ).scalar_one_or_none()
    if not acc:
        acc = AdminAccount(
            username="admin",
            hashed_passkey=hash_password(settings.ADMIN_PASSKEY or "RAIS@516269"),
        )
        db.add(acc)
        await db.commit()
        await db.refresh(acc)

    if not verify_password(payload.passkey.strip(), acc.hashed_passkey):
        rec["count"] += 1
        remaining = max(0, _MAX_ATTEMPTS - int(rec["count"]))
        if rec["count"] >= _MAX_ATTEMPTS:
            rec["locked_until"] = now + _LOCKOUT_SECONDS
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="5 failed attempts. Locked for 60 seconds.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid admin username or passkey. ({remaining} attempts remaining)",
        )

    _FAILED_ATTEMPTS.pop(key, None)
    token = create_access_token({"sub": clean_user, "role": "admin"})
    await log_audit(
        db=db,
        action="ADMIN_LOGIN_SUCCESS",
        resource_type="AUTH",
        resource_id=acc.username,
        actor=clean_user,
        details={"client_ip": key},
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": clean_user,
        "expires_in_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    }


@router.get("/verify")
async def verify_session(admin_user: str = Depends(require_admin)):
    """Verifies that the caller presents a valid, non-expired admin Bearer JWT."""
    return {"authenticated": True, "user": admin_user, "role": "admin"}


@router.post("/change-passkey")
async def change_admin_passkey(
    payload: ChangePasskeyRequest,
    admin_user: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Updates the bcrypt-hashed admin passkey persisted in Neon Postgres."""
    acc = (
        await db.execute(select(AdminAccount).where(AdminAccount.username == "admin"))
    ).scalar_one_or_none()
    if not acc or not verify_password(payload.current_passkey.strip(), acc.hashed_passkey):
        raise HTTPException(status_code=400, detail="Current passkey is incorrect.")

    new_clean = payload.new_passkey.strip()
    if len(new_clean) < 6:
        raise HTTPException(status_code=400, detail="New passkey must be at least 6 characters.")

    acc.hashed_passkey = hash_password(new_clean)
    await db.commit()
    await log_audit(
        db=db,
        action="ADMIN_PASSKEY_CHANGED",
        resource_type="AUTH",
        resource_id=acc.username,
        actor=admin_user,
    )
    return {"status": "SUCCESS", "message": "Admin passkey updated securely in cloud database."}
