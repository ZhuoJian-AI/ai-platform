"""Cryptographic utilities — API key hashing, provider key encryption."""

import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def hash_api_key(key: str) -> str:
    """Hash an API key with SHA-256 for storage (high-entropy, no pepper needed)."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key(scope: str) -> tuple[str, str, str]:
    """Generate a hierarchical API key.

    Returns:
        (full_key, key_prefix, key_hash)
    """
    random_part = secrets.token_urlsafe(32).replace("-", "").replace("_", "")[:32]
    full_key = f"lr_sk_{scope}_{random_part}"
    key_prefix = full_key[:12]
    key_hash = hash_api_key(full_key)
    return full_key, key_prefix, key_hash


def _get_aesgcm() -> AESGCM:
    """Derive an AES-256-GCM key from the master encryption key setting."""
    raw = base64.b64decode(settings.master_encryption_key)
    # AESGCM 要求恰好 16/24/32 字节；若原始 key 不够 32 字节，用 SHA-256 派生
    if len(raw) < 32:
        raw = hashlib.sha256(raw).digest()
    return AESGCM(raw[:32])


def encrypt_provider_api_key(plaintext: str) -> str:
    """Encrypt a secret (provider key, API key, etc.) with AES-256-GCM. Returns base64(nonce + ciphertext)."""
    return _encrypt(plaintext)


def decrypt_provider_api_key(encrypted: str) -> str:
    """Decrypt a secret previously encrypted with encrypt_provider_api_key."""
    return _decrypt(encrypted)


def encrypt_api_key(plaintext: str) -> str:
    """Encrypt an API Key for reversible storage. Returns base64(nonce + ciphertext)."""
    return _encrypt(plaintext)


def decrypt_api_key(encrypted: str) -> str:
    """Decrypt an API Key previously encrypted with encrypt_api_key."""
    return _decrypt(encrypted)


def _encrypt(plaintext: str) -> str:
    """AES-256-GCM encrypt. Returns base64(nonce + ciphertext)."""
    aesgcm = _get_aesgcm()
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def _decrypt(encrypted: str) -> str:
    """AES-256-GCM decrypt. Input is base64(nonce + ciphertext)."""
    aesgcm = _get_aesgcm()
    raw = base64.b64decode(encrypted)
    nonce, ciphertext = raw[:12], raw[12:]
    return aesgcm.decrypt(nonce, ciphertext, None).decode()
