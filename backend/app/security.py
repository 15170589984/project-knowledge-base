import hashlib
import hmac
import secrets
from collections import deque
from datetime import timedelta
from math import ceil
from threading import Lock
from time import monotonic

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlmodel import Session, select

from .models import LoginSession, User, utcnow


PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_HOURS = 12
COOKIE_NAME = "kb_session"
AUTH_ATTEMPT_LIMIT = 5
AUTH_ATTEMPT_WINDOW_SECONDS = 15 * 60


class AuthAttemptLimiter:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.attempts = {}
        self.lock = Lock()

    def consume(self, action: str, subject):
        key = (action, subject)
        now = self.clock()
        with self.lock:
            attempts = self.attempts.setdefault(key, deque())
            while attempts and attempts[0] <= now - AUTH_ATTEMPT_WINDOW_SECONDS:
                attempts.popleft()
            if len(attempts) >= AUTH_ATTEMPT_LIMIT:
                retry_after = max(1, ceil(AUTH_ATTEMPT_WINDOW_SECONDS - (now - attempts[0])))
                raise HTTPException(
                    status_code=429,
                    detail="尝试次数过多，请稍后再试",
                    headers={"Retry-After": str(retry_after)},
                )
            attempts.append(now)
            if len(self.attempts) > 1024:
                self.attempts = {
                    bucket: history
                    for bucket, history in self.attempts.items()
                    if history and history[-1] > now - AUTH_ATTEMPT_WINDOW_SECONDS
                }

    def clear(self, action: str, subject):
        with self.lock:
            self.attempts.pop((action, subject), None)


def hash_password(password: str) -> str:
    return PASSWORD_CONTEXT.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    return PASSWORD_CONTEXT.verify(password, stored_hash)


def token_hash(token: str, secret: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def new_session(db: Session, user: User, secret: str) -> tuple[str, LoginSession]:
    token = secrets.token_urlsafe(32)
    session = LoginSession(
        token_hash=token_hash(token, secret),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=utcnow() + timedelta(hours=SESSION_HOURS),
    )
    db.add(session)
    db.commit()
    return token, session


def get_db(request: Request):
    with Session(request.app.state.engine) as db:
        yield db


def current_identity(request: Request, db: Session = Depends(get_db)) -> tuple[User, LoginSession]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    session = db.get(LoginSession, token_hash(token, request.app.state.settings.session_secret))
    if session is None or session.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已停用")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(sent, session.csrf_token):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请求校验失败")
    return user, session


def current_user(identity: tuple[User, LoginSession] = Depends(current_identity)) -> User:
    return identity[0]


def make_fernet(settings):
    try:
        return Fernet(settings.fernet_key.encode())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("FERNET_KEY is invalid") from exc
