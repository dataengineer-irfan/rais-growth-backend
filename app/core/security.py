import base64
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_bearer_scheme = HTTPBearer(auto_error=False)

# Key derivation from settings
_RAW_KEY = bytes.fromhex(settings.TOKEN_ENCRYPTION_KEY[:64])
_AESGCM = AESGCM(_RAW_KEY)

def encrypt_token(plain_token: str) -> str:
    """Encrypts an OAuth token at rest using AES-GCM 256."""
    if not plain_token:
        return ""
    nonce = os.urandom(12)
    ciphertext = _AESGCM.encrypt(nonce, plain_token.encode('utf-8'), None)
    # Pack nonce + ciphertext
    packed = nonce + ciphertext
    return base64.b64encode(packed).decode('utf-8')

def decrypt_token(encrypted_token_b64: str) -> str:
    """Decrypts an OAuth token stored at rest."""
    if not encrypted_token_b64:
        return ""
    try:
        packed = base64.b64decode(encrypted_token_b64.encode('utf-8'))
        nonce = packed[:12]
        ciphertext = packed[12:]
        decrypted = _AESGCM.decrypt(nonce, ciphertext, None)
        return decrypted.decode('utf-8')
    except Exception:
        return ""

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decodes and validates an HS256 admin JWT token."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("sub"):
            return None
        return payload
    except JWTError:
        return None


async def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency enforcing authenticated admin JWT Bearer session."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    if not payload or payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin session token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return str(payload["sub"])


async def verify_cron_or_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    cron_key: Optional[str] = Query(default=None),
    background: bool = Query(default=False),
) -> str:
    """
    Allows authenticated admins, or external cron triggers (when CRON_SECRET matches,
    or idempotent background=true cron pings when CRON_SECRET is not configured yet).
    """
    if credentials is not None and credentials.scheme.lower() == "bearer":
        payload = decode_access_token(credentials.credentials)
        if payload and payload.get("role") == "admin":
            return str(payload["sub"])

    if settings.CRON_SECRET:
        if cron_key and hmac.compare_digest(cron_key, settings.CRON_SECRET):
            return "cron"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid admin Bearer token or cron_key required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if background:
        return "cron-background"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Admin authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
