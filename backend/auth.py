import os
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional

import bcrypt
import httpx
from fastapi import Depends, Header, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

TOKEN_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _get_serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("AUTH_SECRET")
    if not secret:
        raise RuntimeError("AUTH_SECRET must be set in the backend .env file")
    return URLSafeTimedSerializer(secret, salt="equilibrium-auth")


def _neon_http_query(sql: str, params: Optional[list] = None) -> List[Dict[str, Any]]:
    """
    Execute a SQL query against Neon via its serverless HTTP API (port 443).
    This avoids the need for an open TCP/5432 connection.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL must be set in the backend .env file")

    parsed = urlparse(db_url)
    host = parsed.hostname          # e.g. ep-raspy-...neon.tech
    user = parsed.username
    password = parsed.password
    dbname = parsed.path.lstrip("/")  # e.g. neondb

    # Build a clean connection string for the header (no TCP-only params like channel_binding)
    clean_conn_str = f"postgresql://{user}:{password}@{host}/{dbname}?sslmode=require"

    endpoint = f"https://{host}/sql"

    payload: Dict[str, Any] = {"query": sql}
    if params:
        payload["params"] = [str(p) if not isinstance(p, (int, float, bool, type(None))) else p for p in params]

    response = httpx.post(
        endpoint,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Neon-Connection-String": clean_conn_str,
        },
        timeout=15,
    )

    if response.status_code != 200:
        raise RuntimeError(f"Neon HTTP API error {response.status_code}: {response.text}")

    data = response.json()
    return data.get("rows", [])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def _load_users() -> List[Dict[str, Any]]:
    """Fetch all users from the Neon database."""
    return _neon_http_query("SELECT email, password_hash, role, name FROM users ORDER BY email")


def ensure_default_admin() -> None:
    """Create the first admin account from env vars when no users exist."""
    rows = _neon_http_query("SELECT COUNT(*) AS cnt FROM users")
    count = int(rows[0]["cnt"]) if rows else 0
    if count > 0:
        return

    email = os.getenv("ADMIN_EMAIL", "admin@pership.com").strip().lower()
    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        raise RuntimeError(
            "No users found. Set ADMIN_EMAIL and ADMIN_PASSWORD in backend .env to create the first admin."
        )

    _neon_http_query(
        "INSERT INTO users (email, password_hash, role, name) VALUES ($1, $2, $3, $4) ON CONFLICT (email) DO NOTHING",
        [email, hash_password(password), "admin", "Admin"],
    )


def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    normalized = email.strip().lower()
    rows = _neon_http_query(
        "SELECT email, password_hash, role, name FROM users WHERE email = $1",
        [normalized],
    )
    if rows and verify_password(password, rows[0]["password_hash"]):
        return dict(rows[0])
    return None


def create_access_token(user: Dict[str, Any]) -> str:
    payload = {"email": user["email"], "role": user["role"], "name": user.get("name", "")}
    return _get_serializer().dumps(payload)


def decode_access_token(token: str) -> Dict[str, Any]:
    try:
        return _get_serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except SignatureExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        ) from exc
    except BadSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
        ) from exc


def public_user(user: Dict[str, Any]) -> Dict[str, str]:
    return {
        "email": user["email"],
        "role": user["role"],
        "name": user.get("name", ""),
    }


def list_users_public() -> List[Dict[str, str]]:
    return [public_user(user) for user in _load_users()]


def create_user(email: str, password: str, name: str, role: str = "user") -> Dict[str, str]:
    normalized = email.strip().lower()
    if role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'.")

    existing = _neon_http_query(
        "SELECT email FROM users WHERE email = $1", [normalized]
    )
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email already exists.")

    display_name = name.strip() or normalized.split("@")[0]
    _neon_http_query(
        "INSERT INTO users (email, password_hash, role, name) VALUES ($1, $2, $3, $4)",
        [normalized, hash_password(password), role, display_name],
    )
    return {"email": normalized, "role": role, "name": display_name}


def delete_user(email: str, current_email: str) -> None:
    normalized = email.strip().lower()
    if normalized == current_email:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")

    rows = _neon_http_query("SELECT email FROM users WHERE email = $1", [normalized])
    if not rows:
        raise HTTPException(status_code=404, detail="User not found.")

    _neon_http_query("DELETE FROM users WHERE email = $1", [normalized])


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header.",
        )
    return authorization.removeprefix("Bearer ").strip()


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    token = _extract_bearer_token(authorization)
    return decode_access_token(token)


async def require_admin(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user
