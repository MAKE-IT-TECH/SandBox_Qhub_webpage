"""
Autenticação simples com JWT.
"""

import bcrypt
import jwt
from datetime import datetime, timedelta
from db import get_db
from config import JWT_SECRET, JWT_EXPIRY_HOURS


def authenticate(email: str, password: str) -> dict | None:
    """Valida credenciais e devolve token + info do user."""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not user:
        return None
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return None

    token = jwt.encode(
        {
            "user_id": user["id"],
            "nome": user["nome"],
            "role": user["role"],
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"token": token, "nome": user["nome"], "role": user["role"]}


def verify_token(token: str) -> dict | None:
    """Verifica e descodifica um JWT. Devolve payload ou None."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
