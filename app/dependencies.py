"""Reusable FastAPI dependencies: current-user resolution from the bearer token."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from collections.abc import Callable

from .core.security import decode_access_token
from .database import get_db
from .models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    subject = decode_access_token(token)
    if subject is None:
        raise credentials_error
    user = db.get(User, int(subject))
    if user is None:
        raise credentials_error
    return user


def require_role(*allowed: str) -> Callable[[User], User]:
    """Dependency factory enforcing the current user holds one of `allowed` roles
    (ADMIN always passes)."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role != Role.ADMIN and user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {' or '.join(allowed)}",
            )
        return user
    return checker
