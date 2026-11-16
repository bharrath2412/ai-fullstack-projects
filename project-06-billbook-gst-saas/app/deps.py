"""FastAPI dependencies: one DB connection per request, and the auth/role gate.

The tenant id used by every query comes from here — from the verified token, not
from a header, query parameter or request body. That is the whole multi-tenancy
model, and it is why a handler can never be tricked into reading another shop's
data by passing a different id.
"""

from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, Header, Request

from .config import Settings
from .db import connect
from .security import AuthError, bearer_token, decode_token


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    settings: Settings = request.app.state.settings
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


class Principal(dict):
    """Authenticated caller: user id, tenant id and role, plus their row."""

    @property
    def user_id(self) -> int:
        return int(self["id"])

    @property
    def tenant_id(self) -> int:
        return int(self["tenant_id"])

    @property
    def role(self) -> str:
        return str(self["role"])


def current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Principal:
    from fastapi import HTTPException

    try:
        token = bearer_token(authorization)
        claims = decode_token(token, secret=settings.jwt_secret)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    row = conn.execute(
        "SELECT * FROM users WHERE id = ? AND tenant_id = ?", (int(claims["sub"]), int(claims["tid"]))
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="user no longer exists")
    # The DB is the source of truth for the role; a stale token cannot escalate.
    principal = Principal(
        id=row["id"], tenant_id=row["tenant_id"], role=row["role"], email=row["email"], name=row["name"]
    )
    return principal


def require_roles(*roles: str):
    """Dependency factory enforcing the RBAC matrix declared in the README."""

    def guard(user: Principal = Depends(current_user)) -> Principal:
        from fastapi import HTTPException

        if user.role not in roles:
            allowed = ", ".join(sorted(roles))
            raise HTTPException(
                status_code=403, detail=f"role '{user.role}' is not allowed here (needs: {allowed})"
            )
        return user

    return guard
