"""共享密码哈希工具 — 供 admin / user 等多个认证域复用。"""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """使用 bcrypt 哈希密码。"""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码。"""
    return bcrypt.checkpw(plain.encode(), hashed.encode())
