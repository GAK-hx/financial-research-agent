from __future__ import annotations

import re
import secrets
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel

from financial_research_agent.config import Settings


_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


class RequestIdentity(BaseModel):
    tenant_id: str
    user_id: str
    role: Literal["researcher", "admin"] = "researcher"


def resolve_identity(request: Request, settings: Settings) -> RequestIdentity:
    """Resolve identity at the HTTP boundary; business payload identity is ignored."""

    if settings.identity_mode == "local":
        return RequestIdentity(
            tenant_id="local", user_id="local", role="admin"
        )

    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    if (
        scheme.lower() != "bearer"
        or not settings.agent_api_key
        or not secrets.compare_digest(credential, settings.agent_api_key)
    ):
        raise HTTPException(
            status_code=401,
            detail="AUTHENTICATION_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    tenant_id = request.headers.get("x-tenant-id", "")
    user_id = request.headers.get("x-user-id", "")
    role = request.headers.get("x-agent-role", "researcher").lower()
    if not _IDENTIFIER.fullmatch(tenant_id) or not _IDENTIFIER.fullmatch(user_id):
        raise HTTPException(status_code=400, detail="INVALID_IDENTITY_HEADERS")
    if role not in {"researcher", "admin"}:
        raise HTTPException(status_code=403, detail="ROLE_NOT_ALLOWED")
    return RequestIdentity(tenant_id=tenant_id, user_id=user_id, role=role)


def require_admin(identity: RequestIdentity) -> None:
    if identity.role != "admin":
        raise HTTPException(status_code=403, detail="ADMIN_ROLE_REQUIRED")
