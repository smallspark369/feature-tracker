"""Authentication via Telegram Mini App initData.

Telegram signs the data it injects into a Mini App with HMAC-SHA256 keyed off
the bot token, so the backend can trust the user identity without any login.
Docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from .config import settings

MAX_AGE_SECONDS = 24 * 3600  # initData is re-issued on every app launch


def verify_init_data(init_data: str, bot_token: str) -> dict:
    """Validate the signature and return the Telegram user object."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise ValueError("bad signature")

    auth_date = int(pairs.get("auth_date", "0"))
    if auth_date and time.time() - auth_date > MAX_AGE_SECONDS:
        raise ValueError("stale auth data")

    user = json.loads(pairs.get("user", "{}"))
    if "id" not in user:
        raise ValueError("no user in init data")
    return user


def _display_name(user: dict) -> str:
    name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p).strip()
    return name or (user.get("username") or f"user {user['id']}")


async def current_user(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency. Expects `Authorization: tma <initData>`."""
    from .bot import resolve_admin_ids  # late import to avoid cycles

    scheme, _, data = authorization.partition(" ")
    if scheme.lower() == "tma" and data:
        try:
            user = verify_init_data(data, settings.bot_token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid Telegram signature.")
        return {
            "id": user["id"],
            "name": _display_name(user),
            "username": user.get("username"),
            "is_admin": user["id"] in await resolve_admin_ids(),
        }

    # Local-development escape hatch (see DEV_USER_ID in .env.example).
    if settings.dev_user_id is not None:
        return {
            "id": settings.dev_user_id,
            "name": "Dev",
            "username": None,
            "is_admin": settings.dev_user_id in await resolve_admin_ids(),
        }

    raise HTTPException(status_code=401, detail="Open this app from inside Telegram.")
