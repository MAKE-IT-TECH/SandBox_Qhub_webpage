"""
Autenticação simples com JWT.
"""

import os
import bcrypt
import jwt
from datetime import datetime, timedelta
from db import get_db

SECRET_KEY = os.environ.get("JWT_SECRET", "qhub-poc-secret-mude-em-producao")


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
            "exp": datetime.utcnow() + timedelta(hours=8),
        },
        SECRET_KEY,
        algorithm="HS256",
    )
    return {"token": token, "nome": user["nome"], "role": user["role"]}


def verify_token(token: str) -> dict | None:
    """Verifica e descodifica um JWT. Devolve payload ou None."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
