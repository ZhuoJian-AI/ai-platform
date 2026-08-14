"""FastAPI dependency injection helpers."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

# Type alias for injected DB session
DbSession = Annotated[AsyncSession, Depends(get_db)]
