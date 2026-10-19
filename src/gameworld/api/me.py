"""Selbstauskunft für alle angemeldeten Konten: wer bin ich, welche Rolle habe ich."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from gameworld.access.roles import MSG_UNAVAILABLE, RolesDep, RoleUnavailableError, UserDep, role_of

router = APIRouter(prefix="/api")


class MeOut(BaseModel):
    user_id: str
    display_name: str
    role: str


@router.get("/me")
async def me(uid: UserDep, roles: RolesDep) -> MeOut:
    try:
        profile = await roles.profile(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    return MeOut(user_id=profile.user_id, display_name=profile.display_name, role=role_of(profile))
