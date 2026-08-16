import base64
import os
import secrets
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core import config

# ------------------------------------------------------------------------------
# 1. Password Hashing Utilities using direct bcrypt
# ------------------------------------------------------------------------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    # Use 4 rounds in testing for instant hashing, 12 rounds in production
    rounds = 4 if os.getenv("TESTING", "").lower() == "true" or "test" in config.DATABASE_URL else 12
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

# ------------------------------------------------------------------------------
# 2. JWT Token Generation & Verification
# ------------------------------------------------------------------------------
def create_access_token(
    subject: str, 
    app_name: str, 
    is_admin: bool = False, 
    enable_encryption: bool = False,
    encryption_key: Optional[str] = None,
    expires_delta: Optional[timedelta] = None
) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(seconds=config.DEFAULT_TOKEN_EXPIRY_SECONDS)
        
    to_encode = {
        "sub": subject,
        "app_name": app_name,
        "is_admin": is_admin,
        "enable_encryption": enable_encryption,
        "encryption_key": encryption_key,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    encoded_jwt = jwt.encode(to_encode, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

# ------------------------------------------------------------------------------
# 3. AES-256-GCM Symmetrical Payload Encryption & Decryption
# ------------------------------------------------------------------------------
def generate_aes_key() -> str:
    """Generates a random 256-bit AES key encoded in base64."""
    key_bytes = AESGCM.generate_key(bit_length=256)
    return base64.b64encode(key_bytes).decode("utf-8")

def encrypt_payload(plaintext: str, base64_key: str) -> Dict[str, str]:
    """
    Encrypts plaintext using AES-256-GCM.
    Returns dictionary with base64 encoded ciphertext, IV (nonce), and auth tag.
    """
    key = base64.b64decode(base64_key.encode("utf-8"))
    aesgcm = AESGCM(key)
    iv = os.urandom(12)  # 96-bit recommended nonce for GCM
    
    encrypted_bytes = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    ciphertext_bytes = encrypted_bytes[:-16]
    tag_bytes = encrypted_bytes[-16:]

    return {
        "ciphertext": base64.b64encode(ciphertext_bytes).decode("utf-8"),
        "iv": base64.b64encode(iv).decode("utf-8"),
        "tag": base64.b64encode(tag_bytes).decode("utf-8")
    }

def decrypt_payload(encrypted_dict: Dict[str, str], base64_key: str) -> str:
    """
    Decrypts AES-256-GCM ciphertext using IV and authentication tag.
    """
    key = base64.b64decode(base64_key.encode("utf-8"))
    aesgcm = AESGCM(key)
    iv = base64.b64decode(encrypted_dict["iv"].encode("utf-8"))
    ciphertext = base64.b64decode(encrypted_dict["ciphertext"].encode("utf-8"))
    tag = base64.b64decode(encrypted_dict["tag"].encode("utf-8"))
    
    combined = ciphertext + tag
    decrypted_bytes = aesgcm.decrypt(iv, combined, None)
    return decrypted_bytes.decode("utf-8")
