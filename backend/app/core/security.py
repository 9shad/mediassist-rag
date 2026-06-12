from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings
from app.core.enums import DEMO_USERS, ROLE_COLLECTIONS, Role
from app.core.exceptions import AuthenticationError


def authenticate_user(username: str, password: str) -> dict:
    user = DEMO_USERS.get(username)
    if not user or user["password"] != password:
        raise AuthenticationError("Invalid username or password")
    return user


def create_access_token(role: Role, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role.value,
        "collections": ROLE_COLLECTIONS[role],
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiration_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        raise AuthenticationError("Invalid or expired token")
