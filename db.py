"""
Setup SQLite + helpers para users, agentes e conversas.
"""

import sqlite3
import json
import os
import bcrypt
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "qhub.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            tools TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_agentes (
            user_id INTEGER,
            agente_id INTEGER,
            PRIMARY KEY (user_id, agente_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (agente_id) REFERENCES agentes(id)
        );
        CREATE TABLE IF NOT EXISTS conversas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            agente_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (agente_id) REFERENCES agentes(id)
        );
        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversa_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (conversa_id) REFERENCES conversas(id)
        );
        CREATE TABLE IF NOT EXISTS dashboards (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            html TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    conn.commit()

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        _seed(conn)

    conn.close()


def _seed(conn):
    # --- Users ---
    maria_hash = bcrypt.hashpw(b"maria123", bcrypt.gensalt()).decode()
    rui_hash = bcrypt.hashpw(b"rui123", bcrypt.gensalt()).decode()
    admin_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()

    conn.execute(
        "INSERT INTO users (nome, email, password_hash, role) VALUES (?, ?, ?, ?)",
        ("Maria", "maria@demo.com", maria_hash, "operadora"),
    )
    conn.execute(
        "INSERT INTO users (nome, email, password_hash, role) VALUES (?, ?, ?, ?)",
        ("Rui", "rui@demo.com", rui_hash, "responsavel"),
    )
    conn.execute(
        "INSERT INTO users (nome, email, password_hash, role) VALUES (?, ?, ?, ?)",
        ("Admin", "admin@demo.com", admin_hash, "admin"),
    )

    # --- Agentes ---
    qualidade_prompt = (
        "Es um assistente de qualidade industrial numa fábrica de pintura de peças plásticas para automóveis. "
        "O teu papel é ajudar operadores a identificar e reportar defeitos de pintura. "
        "Quando o utilizador perguntar sobre defeitos, usa as ferramentas disponíveis para consultar os dados reais. "
        "Responde sempre em português, de forma clara e concisa. "
        "Foca-te em alertas: quais são os defeitos mais frequentes, se há picos anormais, "
        "e sugestões práticas para o operador no chão de fábrica.\n\n"
        "VISUALIZAÇÃO:\n"
        "- Para respostas rápidas no chat: usa gerar_kpi, gerar_grafico e gerar_tabela.\n"
        "- Quando o utilizador pedir um relatório, dashboard ou análise completa: usa gerar_dashboard.\n\n"
        "DASHBOARDS (gerar_dashboard):\n"
        "Gera HTML completo para uma página de dashboard. O HTML é inserido dentro de um template que já inclui "
        "Chart.js e estilos base. Escreve o conteúdo HTML do <body>: divs, canvas para gráficos, tabelas, KPIs. "
        "Para gráficos Chart.js, usa <canvas id='...''></canvas> seguido de <script>new Chart(...)</script>. "
        "Usa classes CSS disponíveis: .kpi-card, .chart-container, .data-table, .dashboard-grid, .dashboard-row."
    )

    analise_prompt = (
        "Es um assistente de análise de qualidade numa fábrica de pintura de peças plásticas para automóveis. "
        "O teu papel é ajudar responsáveis de produção a identificar padrões e tendências nos defeitos de pintura. "
        "Quando o utilizador perguntar sobre dados, usa as ferramentas disponíveis para consultar os registos reais. "
        "Responde sempre em português. "
        "Foca-te em análise comparativa: diferenças entre turnos, evolução temporal, "
        "correlações entre tipos de defeito e materiais, e recomendações baseadas nos dados.\n\n"
        "VISUALIZAÇÃO:\n"
        "- Para respostas rápidas no chat: usa gerar_kpi, gerar_grafico e gerar_tabela.\n"
        "- Quando o utilizador pedir um relatório, dashboard ou análise completa: usa gerar_dashboard.\n\n"
        "DASHBOARDS (gerar_dashboard):\n"
        "Gera HTML completo para uma página de dashboard. O HTML é inserido dentro de um template que já inclui "
        "Chart.js e estilos base. Escreve o conteúdo HTML do <body>: divs, canvas para gráficos, tabelas, KPIs. "
        "Para gráficos Chart.js, usa <canvas id='...'></canvas> seguido de <script>new Chart(...)</script>. "
        "Usa classes CSS disponíveis: .kpi-card, .chart-container, .data-table, .dashboard-grid, .dashboard-row. "
        "Cria dashboards ricos com múltiplos gráficos, KPIs e tabelas para dar uma visão completa."
    )

    conn.execute(
        "INSERT INTO agentes (nome, system_prompt, tools) VALUES (?, ?, ?)",
        ("Qualidade", qualidade_prompt, json.dumps(["contar_defeitos", "top_defeitos", "gerar_grafico", "gerar_tabela", "gerar_kpi", "gerar_dashboard"])),
    )
    conn.execute(
        "INSERT INTO agentes (nome, system_prompt, tools) VALUES (?, ?, ?)",
        (
            "Análise",
            analise_prompt,
            json.dumps(["contar_defeitos", "top_defeitos", "defeitos_por_turno", "gerar_grafico", "gerar_tabela", "gerar_kpi", "gerar_dashboard"]),
        ),
    )

    # --- Associações user ↔ agente ---
    conn.execute("INSERT INTO user_agentes (user_id, agente_id) VALUES (1, 1)")  # Maria → Qualidade
    conn.execute("INSERT INTO user_agentes (user_id, agente_id) VALUES (2, 1)")  # Rui → Qualidade
    conn.execute("INSERT INTO user_agentes (user_id, agente_id) VALUES (2, 2)")  # Rui → Análise
    conn.execute("INSERT INTO user_agentes (user_id, agente_id) VALUES (3, 1)")  # Admin → Qualidade
    conn.execute("INSERT INTO user_agentes (user_id, agente_id) VALUES (3, 2)")  # Admin → Análise

    conn.commit()
