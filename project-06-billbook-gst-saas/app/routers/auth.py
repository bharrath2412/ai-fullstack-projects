"""Auth: register a tenant + owner, log in, inspect yourself, invite teammates."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..config import Settings
from ..deps import Principal, current_user, get_db, get_settings, require_roles
from ..schemas import LoginIn, RegisterIn, StaffInviteIn, TenantOut, TokenOut, UserOut
from ..security import AuthError, create_token
from ..services import Conflict, authenticate, create_staff_user, list_users, register_tenant

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _token_response(settings: Settings, user: dict, tenant: dict) -> dict:
    token = create_token(
        subject=user["id"],
        tenant_id=tenant["id"],
        role=user["role"],
        secret=settings.jwt_secret,
        ttl_seconds=settings.token_ttl_seconds,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.token_ttl_seconds,
        "user": user,
        "tenant": tenant,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenOut)
def register(
    payload: RegisterIn,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Create a tenant and its owner in one transaction. Returns a ready token."""
    try:
        user, tenant = register_tenant(
            conn,
            tenant_name=payload.tenant_name,
            state_code=payload.state_code,
            gstin=payload.gstin,
            address=payload.address,
            name=payload.name,
            email=payload.email,
            password=payload.password,
        )
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _token_response(settings, user, tenant)


@router.post("/login", response_model=TokenOut)
def login(
    payload: LoginIn,
    conn: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        user, tenant = authenticate(conn, payload.email, payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _token_response(settings, user, tenant)


@router.get("/me", response_model=UserOut)
def me(user: Principal = Depends(current_user)):
    return {"id": user.user_id, "tenant_id": user.tenant_id, "name": user["name"],
            "email": user["email"], "role": user.role}


@router.get("/tenant", response_model=TenantOut)
def tenant(
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(current_user),
):
    """The caller's own tenant — used by the admin UI header after a reload."""
    from ..services import get_tenant

    return get_tenant(conn, user.tenant_id)


@router.get("/users", response_model=list[UserOut])
def users(
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner")),
):
    return list_users(conn, user.tenant_id)


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def invite(
    payload: StaffInviteIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: Principal = Depends(require_roles("owner")),
):
    try:
        return create_staff_user(
            conn,
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            name=payload.name,
            email=payload.email,
            password=payload.password,
            role=payload.role,
        )
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    """Tokens are stateless; the client drops it. Endpoint exists for symmetry."""
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
