"""Password hashing and JWT issuing/verification, standard library only.

Why not PyJWT? Because this project's point is that you can read every line of the
security code. HS256 is HMAC-SHA256 over `header.payload`, so `hmac` + `base64url`
is the whole implementation — and because it is ours, we can be strict about the
things libraries get configured wrong: the `alg` header is checked, `alg: none`
is refused, `exp` is mandatory, and signature comparison is constant-time.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

PBKDF2_ROUNDS = 120_000
DEFAULT_TTL_SECONDS = 8 * 60 * 60


class AuthError(Exception):
    """Raised when a token or password cannot be trusted."""


# --------------------------------------------------------------------------- #
# passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str, *, rounds: int = PBKDF2_ROUNDS) -> str:
    """Return `pbkdf2_sha256$rounds$salt_hex$hash_hex`."""
    if not password or len(password) < 8:
        raise AuthError("password must be at least 8 characters")
    if len(password) > 200:
        raise AuthError("password must be at most 200 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of a password against a stored hash."""
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
    except (ValueError, TypeError, AttributeError):
        return False
    return hmac.compare_digest(candidate, expected)


# --------------------------------------------------------------------------- #
# base64url helpers
# --------------------------------------------------------------------------- #
def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (binascii.Error, ValueError) as exc:
        raise AuthError("malformed base64 segment in token") from exc


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_token(
    *,
    subject: str | int,
    tenant_id: int,
    role: str,
    secret: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    extra: dict[str, Any] | None = None,
    now: int | None = None,
) -> str:
    issued = int(now if now is not None else time.time())
    payload: dict[str, Any] = {
        "sub": str(subject),
        "tid": int(tenant_id),
        "role": role,
        "iat": issued,
        "exp": issued + int(ttl_seconds),
        "jti": secrets.token_hex(8),
    }
    if extra:
        payload.update(extra)
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join(
        _b64encode(json.dumps(part, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        for part in (header, payload)
    )
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_token(token: str, *, secret: str, now: int | None = None) -> dict[str, Any]:
    """Verify signature + claims and return the payload. Raises AuthError."""
    if not token or not isinstance(token, str):
        raise AuthError("missing token")
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("token must have three segments")
    header_b64, payload_b64, signature_b64 = parts
    expected_sig = hmac.new(
        secret.encode("utf-8"), f"{header_b64}.{payload_b64}".encode("ascii"), hashlib.sha256
    ).digest()
    presented_sig = _b64decode(signature_b64)
    if not hmac.compare_digest(expected_sig, presented_sig):
        raise AuthError("signature verification failed")

    header = json.loads(_b64decode(header_b64) or b"{}")
    if header.get("alg") != "HS256":
        raise AuthError(f"unsupported alg: {header.get('alg')!r}")
    payload = json.loads(_b64decode(payload_b64) or b"{}")

    for claim in ("sub", "tid", "role", "exp"):
        if claim not in payload:
            raise AuthError(f"token missing '{claim}' claim")
    timestamp = int(now if now is not None else time.time())
    if int(payload["exp"]) <= timestamp:
        raise AuthError("token expired")
    return payload


def bearer_token(authorization: str | None) -> str:
    """Extract the token from an `Authorization: Bearer …` header."""
    if not authorization:
        raise AuthError("authorization header required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("expected 'Bearer <token>'")
    return token.strip()


def secret_from_env(default_factory=lambda: secrets.token_urlsafe(32)) -> str:
    """Read JWT_SECRET, refusing the well-known placeholder in production."""
    secret = os.environ.get("JWT_SECRET", "").strip()
    if secret:
        if secret in {"changeme", "secret", "dev"} and os.environ.get("ENV", "dev") != "dev":
            raise RuntimeError("JWT_SECRET is a placeholder; set a real one")
        return secret
    return default_factory()
