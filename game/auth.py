import hashlib
import secrets
import time

from django.db import IntegrityError
from .models import User, Session

SESSION_TTL = 86400 * 7


def hash_pw(password: str, salt: bytes = None):
    if salt is None:
        salt = secrets.token_bytes(16)
    return salt, hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    Session.objects.create(token=token, user_id=user_id,
                           expires_at=time.time() + SESSION_TTL)
    return token


def register_user(username: str, password: str):
    if not username or len(username) < 3 or len(password) < 4:
        return None, "Имя ≥3, пароль ≥4 символов"
    salt, pwh = hash_pw(password)
    try:
        u = User.objects.create(username=username, password_hash=pwh, salt=salt,
                                created_at=time.time())
    except IntegrityError:
        return None, "Имя уже занято"
    return {"token": create_session(u.id), "user_id": u.id, "username": u.username}, None


def login_user(username: str, password: str):
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return None, "Неверный логин или пароль"
    _, h = hash_pw(password, bytes(user.salt))
    if not secrets.compare_digest(h, bytes(user.password_hash)):
        return None, "Неверный логин или пароль"
    return {"token": create_session(user.id), "user_id": user.id,
            "username": user.username}, None


def user_by_token(token: str):
    if not token:
        return None
    try:
        s = Session.objects.select_related('user').get(token=token)
    except Session.DoesNotExist:
        return None
    if s.expires_at <= time.time():
        return None
    return s.user