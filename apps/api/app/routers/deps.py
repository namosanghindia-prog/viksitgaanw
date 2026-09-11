"""Shared FastAPI dependencies for the routers that act as the device owner."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Profile
from ..services.profiles import get_owner


def owner(session: Session = Depends(get_session)) -> Profile:
    """The device owner; 409 before onboarding, as the marketplace routes do."""
    profile = get_owner(session)
    if profile is None:
        raise HTTPException(status_code=409, detail="Set up your profile first.")
    return profile


def fail(error: Exception) -> HTTPException:
    """Turn a service error carrying a ``status`` into an HTTP error."""
    return HTTPException(status_code=getattr(error, "status", 409), detail=str(error))
