import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Any
from jose import jwt
import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

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
