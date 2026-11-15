from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv

from app.insurance.database import change_password as update_password
from app.insurance.database import find_account, verify_password

load_dotenv()


class AuthenticationError(ValueError):
    """Raised when credentials or a token are invalid."""


def jwt_secret() -> str:
    secret = os.getenv("APP_JWT_SECRET", "").strip()
    if not secret:
        raise AuthenticationError("APP_JWT_SECRET is not configured.")
    return secret


def authenticate(
    project_root, identifier: str, password: str
) -> dict[str, object]:
    account = find_account(project_root, identifier.strip())
    if not account or not verify_password(password, account["password_hash"]):
        raise AuthenticationError("Invalid credentials.")
    payload = {
        "sub": account["account_id"],
        "role": account["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
    }
    return {
        "access_token": jwt.encode(payload, jwt_secret(), algorithm="HS256"),
        "token_type": "bearer",
        "user_id": account["account_id"],
        "role": account["role"],
        "display_name": account["patient_name"],
        "must_change_password": bool(account["password_is_temporary"]),
    }


def change_password(
    project_root, account_id: str, current_password: str, new_password: str
) -> None:
    try:
        update_password(project_root, account_id, current_password, new_password)
    except ValueError as error:
        raise AuthenticationError(str(error)) from error


def decode_token(token: str) -> dict[str, str]:
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=["HS256"])
        if not payload.get("sub") or not payload.get("role"):
            raise AuthenticationError("Invalid token claims.")
        return {"user_id": payload["sub"], "role": payload["role"]}
    except (jwt.InvalidTokenError, AuthenticationError) as error:
        raise AuthenticationError("Invalid or expired token.") from error
