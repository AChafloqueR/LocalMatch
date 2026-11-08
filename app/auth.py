import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request

from .db import get_db


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), stored)


def current_user(request: Request):
    uid = request.session.get("uid")
    if not uid:
        return None
    with get_db() as db:
        return db.execute("SELECT u.id,u.email,u.name,u.role,u.company_id,c.name AS company FROM users u "
                          "LEFT JOIN companies c ON c.id=u.company_id WHERE u.id=?", (uid,)).fetchone()


class NeedLogin(Exception):
    pass


def require(*roles: str):
    def dep(request: Request):
        user = current_user(request)
        if not user:
            raise NeedLogin()
        if roles and user["role"] not in roles:
            raise HTTPException(status_code=403, detail="No tienes permiso para ver esta página.")
        return user

    return dep
