"""Small RFC 6238 TOTP implementation for administrator MFA."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decoded_secret(secret: str) -> bytes:
    normalized = "".join(secret.upper().split())
    return base64.b32decode(normalized + "=" * ((8 - len(normalized) % 8) % 8))


def totp_at(secret: str, timestamp: int, *, step: int = 30, digits: int = 6) -> str:
    counter = timestamp // step
    digest = hmac.new(_decoded_secret(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset: offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return f"{value:0{digits}d}"


def verify_totp(secret: str, code: str, *, now: int | None = None) -> bool:
    return matching_totp_counter(secret, code, now=now) is not None


def matching_totp_counter(secret: str, code: str, *, now: int | None = None) -> int | None:
    normalized = "".join(code.split())
    if len(normalized) != 6 or not normalized.isdigit():
        return None
    current = int(time.time() if now is None else now)
    for offset in (-1, 0, 1):
        candidate_time = current + offset * 30
        if hmac.compare_digest(totp_at(secret, candidate_time), normalized):
            return candidate_time // 30
    return None


def provisioning_uri(secret: str, username: str, issuer: str = "AI Infra") -> str:
    label = quote(f"{issuer}:{username}", safe="")
    return f"otpauth://totp/{label}?secret={quote(secret)}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def generate_recovery_codes(count: int = 10) -> list[str]:
    # 96 bits per code; grouping is only for human transcription.
    return ["-".join(secrets.token_hex(12)[i:i + 4] for i in range(0, 24, 4)) for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    normalized = code.replace("-", "").strip().lower()
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()
