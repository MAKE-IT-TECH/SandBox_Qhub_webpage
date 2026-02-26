"""
Configuração centralizada — carrega variáveis de ambiente do ficheiro .env.
"""

import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
JWT_SECRET: str = os.environ.get("JWT_SECRET", "qhub-poc-secret-mude-em-producao")
JWT_EXPIRY_HOURS: int = int(os.environ.get("JWT_EXPIRY_HOURS", "8"))
