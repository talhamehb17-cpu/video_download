"""Administrator sign-in.

* One account. It is created from ``ADMIN_EMAIL`` and ``ADMIN_BOOTSTRAP_PASSWORD``
  the first time the service starts and is kept in ``admin.json`` in the data
  directory (owner-only permissions). The bootstrap password must be replaced at
  the first sign-in and never works again afterwards.
* Passwords are stored as scrypt hashes with a random salt, never in clear.
* A sign-in returns a random token. The server keeps only its SHA-256, so a copy
  of the server's memory or files cannot be replayed. Sessions end after a period
  without requests, after a fixed lifetime, at sign-out, at every password change
  and when the service restarts.
* Wrong passwords pause sign-in for the account, longer each time, on top of the
  per-address rate limit of the endpoint.

To start over (forgotten password): delete ``admin.json`` and restart the service.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.errors import AppError

log = logging.getLogger("lumora.admin")

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
MAX_SESSIONS = 20
_SCRYPT_N_LOG2, _SCRYPT_R, _SCRYPT_P, _KEY_BYTES = 15, 8, 1, 32
_LOCK_BASE_SECONDS, _LOCK_MAX_SECONDS = 60, 3600


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=1 << _SCRYPT_N_LOG2, r=_SCRYPT_R, p=_SCRYPT_P,
        dklen=_KEY_BYTES, maxmem=128 * 1024 * 1024,
    )
    return f"scrypt${_SCRYPT_N_LOG2}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n_log2, r, p, salt_text, key_text = encoded.split("$")
        if scheme != "scrypt" or not 10 <= int(n_log2) <= 20:
            return False
        salt, expected = base64.b64decode(salt_text), base64.b64decode(key_text)
        key = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=1 << int(n_log2), r=int(r), p=int(p),
            dklen=len(expected), maxmem=128 * 1024 * 1024,
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(key, expected)


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Session:
    digest: str
    created_at: float
    last_seen: float
    must_change_password: bool

    def expires_at(self, idle: float, lifetime: float) -> float:
        return min(self.last_seen + idle, self.created_at + lifetime)


@dataclass
class Account:
    email: str
    password_hash: str
    must_change_password: bool
    updated_at: float


class AdminAuth:
    def __init__(self, settings: Settings) -> None:
        self._idle = settings.admin_session_minutes * 60.0
        self._lifetime = settings.admin_session_max_hours * 3600.0
        self._max_failures = settings.admin_max_failed_logins
        self._path: Path = settings.data_dir / "admin.json"
        secret = settings.admin_bootstrap_password
        self._bootstrap = secret.get_secret_value() if secret else None
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self._failures = 0
        self._lockouts = 0
        self._locked_until = 0.0
        self.persistent = True
        self._account = self._load()
        if self._account is None and settings.admin_email and self._bootstrap:
            self._account = Account(settings.admin_email, hash_password(self._bootstrap), True, time.time())
            self._save()
            log.info("administrator account created for %s; the password must be changed at the first sign-in",
                     settings.admin_email)

    # ------------------------------------------------------------------ storage
    def _load(self) -> Account | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return Account(
                email=str(data["email"]).lower(), password_hash=str(data["password_hash"]),
                must_change_password=bool(data.get("must_change_password")),
                updated_at=float(data.get("updated_at") or 0),
            )
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.error("the administrator file %s is unreadable (%s); sign-in stays off until it is fixed or deleted",
                      self._path, exc)
            self.persistent = False
            return None

    def _save(self) -> None:
        account = self._account
        if account is None:
            return
        payload = json.dumps({
            "email": account.email, "password_hash": account.password_hash,
            "must_change_password": account.must_change_password, "updated_at": account.updated_at,
        })
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temp = tempfile.mkstemp(dir=self._path.parent, prefix=".admin-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.chmod(temp, 0o600)
                os.replace(temp, self._path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            self.persistent = True
        except OSError as exc:
            log.error("the administrator account could not be saved to %s (%s): a new password will be lost "
                      "when the service restarts", self._path, exc)
            self.persistent = False

    # ------------------------------------------------------------------ state
    @property
    def configured(self) -> bool:
        return self._account is not None

    @property
    def email(self) -> str | None:
        return self._account.email if self._account else None

    def _prune(self, now: float) -> None:
        for digest in [d for d, s in self._sessions.items() if s.expires_at(self._idle, self._lifetime) <= now]:
            del self._sessions[digest]

    def _open_session(self, now: float, must_change: bool) -> tuple[str, Session]:
        self._prune(now)
        while len(self._sessions) >= MAX_SESSIONS:
            del self._sessions[min(self._sessions, key=lambda d: self._sessions[d].last_seen)]
        token = secrets.token_urlsafe(32)
        session = Session(_token_digest(token), now, now, must_change)
        self._sessions[session.digest] = session
        return token, session

    def expires_at(self, session: Session) -> float:
        return session.expires_at(self._idle, self._lifetime)

    # ------------------------------------------------------------------ sign-in
    def login(self, email: str, password: str, *, client: str) -> tuple[str, Session]:
        """Check the credentials and open a session. Slow on purpose (one scrypt run)."""
        account = self._account
        if account is None:
            raise AppError("admin_not_configured")
        now = time.time()
        with self._lock:
            if now < self._locked_until:
                raise AppError("too_many_attempts", retry_after=int(self._locked_until - now) + 1)
        known = hmac.compare_digest(email.strip().lower().encode(), account.email.encode())
        valid = verify_password(password[:MAX_PASSWORD_LENGTH], account.password_hash if known else _DUMMY_HASH)
        with self._lock:
            now = time.time()
            if now < self._locked_until:  # another attempt hit the limit while this one was being checked
                raise AppError("too_many_attempts", retry_after=int(self._locked_until - now) + 1)
            if not (known and valid):
                self._failures += 1
                if self._failures >= self._max_failures:
                    self._failures = 0
                    self._lockouts += 1
                    pause = min(_LOCK_MAX_SECONDS, _LOCK_BASE_SECONDS * 2 ** (self._lockouts - 1))
                    self._locked_until = now + pause
                    log.warning("admin sign-in paused for %ds after repeated failures (last from %s)", pause, client)
                else:
                    log.warning("admin sign-in failed from %s", client)
                raise AppError("invalid_credentials")
            self._failures = self._lockouts = 0
            token, session = self._open_session(now, account.must_change_password)
        log.info("admin signed in from %s", client)
        return token, session

    def authenticate(self, token: str | None) -> Session:
        if not token or len(token) > 200:
            raise AppError("not_authenticated")
        now = time.time()
        with self._lock:
            session = self._sessions.get(_token_digest(token))
            if session is None or session.expires_at(self._idle, self._lifetime) <= now:
                if session is not None:
                    del self._sessions[session.digest]
                raise AppError("not_authenticated")
            session.last_seen = now
            return session

    def logout(self, session: Session) -> None:
        with self._lock:
            self._sessions.pop(session.digest, None)

    # ------------------------------------------------------------------ password
    def change_password(self, session: Session, current: str, new: str, *, client: str) -> tuple[str, Session]:
        """Replace the password, end every session and open a fresh one for the caller."""
        account = self._account
        if account is None:
            raise AppError("admin_not_configured")
        if not verify_password(current[:MAX_PASSWORD_LENGTH], account.password_hash):
            log.warning("admin password change refused from %s: current password wrong", client)
            raise AppError("invalid_credentials", message="The current password is wrong.")
        if len(new) < MIN_PASSWORD_LENGTH:
            raise AppError("weak_password", message=f"Use at least {MIN_PASSWORD_LENGTH} characters.")
        if len(new) > MAX_PASSWORD_LENGTH:
            raise AppError("weak_password", message=f"Use at most {MAX_PASSWORD_LENGTH} characters.")
        if hmac.compare_digest(new.encode(), current.encode()) or (
            self._bootstrap is not None and hmac.compare_digest(new.encode(), self._bootstrap.encode())
        ):
            raise AppError("weak_password", message="Choose a password you haven't used here before.")
        if new.strip().lower() in (account.email, account.email.split("@", 1)[0]):
            raise AppError("weak_password", message="Don't use your e-mail address as the password.")
        hashed = hash_password(new)
        with self._lock:
            account.password_hash, account.must_change_password, account.updated_at = hashed, False, time.time()
            self._save()
            self._sessions.clear()
            token, fresh = self._open_session(time.time(), False)
        log.info("admin password changed from %s; all other sessions ended", client)
        return token, fresh
