"""Bearer token authentication dependency for FastAPI."""

from __future__ import annotations

from fastapi import HTTPException, Request, status


def _get_token_from_config(request: Request) -> str:
    """Retrieve the expected token from app state."""
    return request.app.state.config.gateway.token


def verify_token(request: Request) -> str:
    """FastAPI dependency that validates the Bearer token.

    Raises 401 if the token is missing or invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = auth_header[7:]
    expected = _get_token_from_config(request)
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    return token
