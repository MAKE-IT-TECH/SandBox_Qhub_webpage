"""
FastAPI — endpoints API + serve frontend.
"""

import json

import bcrypt
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from db import init_db, get_db
from auth import authenticate, verify_token
from agent_engine import process_message, TOOL_DEFINITIONS

app = FastAPI(title="QHub PoC")


# --- Startup ---

@app.on_event("startup")
def startup():
    init_db()


# --- Auth dependency ---

async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token em falta")
    payload = verify_token(auth[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")
    return payload


# --- Models ---

class LoginRequest(BaseModel):
    email: str
    password: str

class MensagemRequest(BaseModel):
    content: str

class AgenteRequest(BaseModel):
    nome: str
    system_prompt: str
    tools: list[str]

class UserRequest(BaseModel):
    nome: str
    email: str
    password: Optional[str] = None
    role: str

class UserAgentesRequest(BaseModel):
    agente_ids: list[int]


# --- Endpoints ---

@app.post("/auth/login")
async def login(body: LoginRequest):
    result = authenticate(body.email, body.password)
    if not result:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    return result


@app.get("/agentes")
async def listar_agentes(user: dict = Depends(get_current_user)):
    conn = get_db()
    agentes = conn.execute(
        """
        SELECT a.id, a.nome
        FROM agentes a
        JOIN user_agentes ua ON ua.agente_id = a.id
        WHERE ua.user_id = ?
        """,
        (user["user_id"],),
    ).fetchall()
    conn.close()
    return [{"id": a["id"], "nome": a["nome"]} for a in agentes]


@app.post("/conversas")
async def criar_conversa(request: Request, user: dict = Depends(get_current_user)):
    body = await request.json()
    agente_id = body.get("agente_id")
    if not agente_id:
        raise HTTPException(status_code=400, detail="agente_id obrigatório")

    conn = get_db()
    # Verificar permissão
    perm = conn.execute(
        "SELECT 1 FROM user_agentes WHERE user_id = ? AND agente_id = ?",
        (user["user_id"], agente_id),
    ).fetchone()
    if not perm:
        conn.close()
        raise HTTPException(status_code=403, detail="Sem acesso a este agente")

    now = datetime.utcnow().isoformat()
    cursor = conn.execute(
        "INSERT INTO conversas (user_id, agente_id, created_at) VALUES (?, ?, ?)",
        (user["user_id"], agente_id, now),
    )
    conn.commit()
    conversa_id = cursor.lastrowid
    conn.close()
    return {"id": conversa_id, "agente_id": agente_id, "created_at": now}


@app.get("/conversas")
async def listar_conversas(user: dict = Depends(get_current_user)):
    conn = get_db()
    conversas = conn.execute(
        """
        SELECT c.id, c.agente_id, a.nome as agente_nome, c.created_at
        FROM conversas c
        JOIN agentes a ON a.id = c.agente_id
        WHERE c.user_id = ?
        ORDER BY c.created_at DESC
        """,
        (user["user_id"],),
    ).fetchall()
    conn.close()
    return [
        {
            "id": c["id"],
            "agente_id": c["agente_id"],
            "agente_nome": c["agente_nome"],
            "created_at": c["created_at"],
        }
        for c in conversas
    ]


@app.get("/conversas/{conversa_id}/mensagens")
async def listar_mensagens(conversa_id: int, user: dict = Depends(get_current_user)):
    conn = get_db()
    conversa = conn.execute(
        "SELECT * FROM conversas WHERE id = ? AND user_id = ?",
        (conversa_id, user["user_id"]),
    ).fetchone()
    if not conversa:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    msgs = conn.execute(
        "SELECT role, content, timestamp FROM mensagens WHERE conversa_id = ? ORDER BY timestamp",
        (conversa_id,),
    ).fetchall()
    conn.close()
    return [{"role": m["role"], "content": m["content"], "timestamp": m["timestamp"]} for m in msgs]


@app.post("/conversas/{conversa_id}/mensagens")
async def enviar_mensagem(
    conversa_id: int,
    body: MensagemRequest,
    user: dict = Depends(get_current_user),
):
    return StreamingResponse(
        process_message(user["user_id"], conversa_id, body.content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Dashboards ---

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="pt">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{titulo} — QHub</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #1a1a1a; }}
        .dashboard-header {{ background: #1a1a2e; color: #fff; padding: 20px 32px; }}
        .dashboard-header h1 {{ font-size: 22px; font-weight: 600; }}
        .dashboard-header .meta {{ font-size: 13px; opacity: 0.7; margin-top: 4px; }}
        .dashboard-body {{ max-width: 1200px; margin: 24px auto; padding: 0 24px; }}
        .dashboard-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 24px; }}
        .dashboard-row {{ display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 24px; }}
        .kpi-card {{ background: linear-gradient(135deg, #1a1a2e, #16213e); color: #fff; border-radius: 12px; padding: 24px; flex: 1; min-width: 180px; }}
        .kpi-card h3 {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.8; margin-bottom: 8px; }}
        .kpi-card .value {{ font-size: 36px; font-weight: 700; }}
        .kpi-card .unit {{ font-size: 14px; opacity: 0.7; margin-left: 4px; }}
        .kpi-card .variation {{ font-size: 12px; margin-top: 8px; opacity: 0.8; }}
        .chart-container {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 12px; padding: 20px; }}
        .chart-container h3 {{ font-size: 15px; font-weight: 600; margin-bottom: 16px; color: #1a1a2e; }}
        .chart-container canvas {{ max-height: 350px; }}
        .data-table {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 12px; padding: 20px; overflow-x: auto; }}
        .data-table h3 {{ font-size: 15px; font-weight: 600; margin-bottom: 16px; color: #1a1a2e; }}
        .data-table table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        .data-table th {{ background: #f5f7fa; padding: 10px 14px; text-align: left; font-weight: 600; border-bottom: 2px solid #e0e0e0; color: #555; }}
        .data-table td {{ padding: 10px 14px; border-bottom: 1px solid #f0f0f0; }}
        .data-table tr:hover td {{ background: #f8f9fa; }}
        .section-title {{ font-size: 18px; font-weight: 600; margin: 32px 0 16px; color: #1a1a2e; }}
    </style>
</head>
<body>
    <div class="dashboard-header">
        <h1>{titulo}</h1>
        <div class="meta">Gerado em {created_at} — QHub Qualidade Industrial</div>
    </div>
    <div class="dashboard-body">
        {html}
    </div>
    <script>
        // Report height to parent for iframe auto-resize
        function reportHeight() {{
            var h = document.documentElement.scrollHeight;
            window.parent.postMessage({{type: 'dashboard-height', height: h}}, '*');
        }}
        window.addEventListener('load', reportHeight);
        window.addEventListener('resize', reportHeight);
        new MutationObserver(reportHeight).observe(document.body, {{childList: true, subtree: true}});
        setTimeout(reportHeight, 500);
        setTimeout(reportHeight, 1500);
    </script>
</body>
</html>"""


@app.get("/dashboards/{dashboard_id}")
async def ver_dashboard(dashboard_id: str):
    conn = get_db()
    dash = conn.execute(
        "SELECT * FROM dashboards WHERE id = ?", (dashboard_id,)
    ).fetchone()
    conn.close()
    if not dash:
        raise HTTPException(status_code=404, detail="Dashboard não encontrado")

    page = DASHBOARD_TEMPLATE.format(
        titulo=dash["titulo"],
        html=dash["html"],
        created_at=dash["created_at"][:16].replace("T", " "),
    )
    return HTMLResponse(content=page)


# --- Admin dependency ---

async def require_admin(request: Request) -> dict:
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso reservado a administradores")
    return user


# --- Admin: Agentes ---

@app.get("/admin/agentes")
async def admin_listar_agentes(user: dict = Depends(require_admin)):
    conn = get_db()
    agentes = conn.execute("SELECT id, nome, system_prompt, tools FROM agentes").fetchall()
    conn.close()
    return [
        {
            "id": a["id"],
            "nome": a["nome"],
            "system_prompt": a["system_prompt"],
            "tools": json.loads(a["tools"]),
        }
        for a in agentes
    ]


@app.post("/admin/agentes")
async def admin_criar_agente(body: AgenteRequest, user: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO agentes (nome, system_prompt, tools) VALUES (?, ?, ?)",
        (body.nome, body.system_prompt, json.dumps(body.tools)),
    )
    conn.commit()
    agente_id = cursor.lastrowid
    conn.close()
    return {"id": agente_id, "nome": body.nome}


@app.put("/admin/agentes/{agente_id}")
async def admin_atualizar_agente(agente_id: int, body: AgenteRequest, user: dict = Depends(require_admin)):
    conn = get_db()
    existing = conn.execute("SELECT id FROM agentes WHERE id = ?", (agente_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Agente não encontrado")
    conn.execute(
        "UPDATE agentes SET nome = ?, system_prompt = ?, tools = ? WHERE id = ?",
        (body.nome, body.system_prompt, json.dumps(body.tools), agente_id),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.delete("/admin/agentes/{agente_id}")
async def admin_apagar_agente(agente_id: int, user: dict = Depends(require_admin)):
    conn = get_db()
    existing = conn.execute("SELECT id FROM agentes WHERE id = ?", (agente_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Agente não encontrado")
    # Cascata: remover associações, conversas e mensagens
    conversa_ids = conn.execute("SELECT id FROM conversas WHERE agente_id = ?", (agente_id,)).fetchall()
    for c in conversa_ids:
        conn.execute("DELETE FROM mensagens WHERE conversa_id = ?", (c["id"],))
    conn.execute("DELETE FROM conversas WHERE agente_id = ?", (agente_id,))
    conn.execute("DELETE FROM user_agentes WHERE agente_id = ?", (agente_id,))
    conn.execute("DELETE FROM agentes WHERE id = ?", (agente_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


# --- Admin: Tools ---

@app.get("/admin/tools")
async def admin_listar_tools(user: dict = Depends(require_admin)):
    tools = []
    for name, defn in TOOL_DEFINITIONS.items():
        tools.append({
            "name": name,
            "description": defn.get("description", ""),
            "parameters": defn.get("input_schema", {}).get("properties", {}),
        })
    return tools


# --- Admin: Users ---

@app.get("/admin/users")
async def admin_listar_users(user: dict = Depends(require_admin)):
    conn = get_db()
    users = conn.execute("SELECT id, nome, email, role FROM users").fetchall()
    conn.close()
    return [{"id": u["id"], "nome": u["nome"], "email": u["email"], "role": u["role"]} for u in users]


@app.post("/admin/users")
async def admin_criar_user(body: UserRequest, user: dict = Depends(require_admin)):
    if not body.password:
        raise HTTPException(status_code=400, detail="Password obrigatória para criar user")
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (body.email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="Email já registado")
    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    cursor = conn.execute(
        "INSERT INTO users (nome, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (body.nome, body.email, pw_hash, body.role),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return {"id": user_id, "nome": body.nome, "email": body.email, "role": body.role}


@app.put("/admin/users/{user_id}")
async def admin_atualizar_user(user_id: int, body: UserRequest, user: dict = Depends(require_admin)):
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="User não encontrado")
    # Verificar email duplicado
    dup = conn.execute("SELECT id FROM users WHERE email = ? AND id != ?", (body.email, user_id)).fetchone()
    if dup:
        conn.close()
        raise HTTPException(status_code=409, detail="Email já registado por outro user")
    if body.password:
        pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "UPDATE users SET nome = ?, email = ?, password_hash = ?, role = ? WHERE id = ?",
            (body.nome, body.email, pw_hash, body.role, user_id),
        )
    else:
        conn.execute(
            "UPDATE users SET nome = ?, email = ?, role = ? WHERE id = ?",
            (body.nome, body.email, body.role, user_id),
        )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.delete("/admin/users/{user_id}")
async def admin_apagar_user(user_id: int, user: dict = Depends(require_admin)):
    if user_id == user["user_id"]:
        raise HTTPException(status_code=400, detail="Não podes apagar o teu próprio user")
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="User não encontrado")
    # Cascata
    conversa_ids = conn.execute("SELECT id FROM conversas WHERE user_id = ?", (user_id,)).fetchall()
    for c in conversa_ids:
        conn.execute("DELETE FROM mensagens WHERE conversa_id = ?", (c["id"],))
    conn.execute("DELETE FROM conversas WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_agentes WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM dashboards WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/admin/users/{user_id}/agentes")
async def admin_user_agentes(user_id: int, user: dict = Depends(require_admin)):
    conn = get_db()
    agentes = conn.execute(
        "SELECT agente_id FROM user_agentes WHERE user_id = ?", (user_id,)
    ).fetchall()
    conn.close()
    return [a["agente_id"] for a in agentes]


@app.put("/admin/users/{user_id}/agentes")
async def admin_set_user_agentes(user_id: int, body: UserAgentesRequest, user: dict = Depends(require_admin)):
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="User não encontrado")
    conn.execute("DELETE FROM user_agentes WHERE user_id = ?", (user_id,))
    for aid in body.agente_ids:
        conn.execute("INSERT INTO user_agentes (user_id, agente_id) VALUES (?, ?)", (user_id, aid))
    conn.commit()
    conn.close()
    return {"status": "ok"}


# --- Serve frontend ---
app.mount("/", StaticFiles(directory="static", html=True), name="static")
