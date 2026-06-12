from fastapi import Depends, Header

from app.core.enums import ROLE_COLLECTIONS, Role
from app.core.exceptions import AuthorizationError
from app.core.security import decode_access_token


def get_current_user(authorization: str = Header(...)) -> dict:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise AuthorizationError("Invalid authorization scheme")
    payload = decode_access_token(token)
    return payload


def require_role(payload: dict = Depends(get_current_user)) -> dict:
    return payload


def get_role_collections(role: str) -> list[str]:
    try:
        return ROLE_COLLECTIONS[Role(role)]
    except (KeyError, ValueError):
        raise AuthorizationError(f"Unknown role: {role}")
