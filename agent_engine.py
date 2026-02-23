"""
Core de agentes: system prompts, tool dispatch, streaming via SSE.
"""

import json
import os
import uuid
from datetime import datetime

import anthropic

from db import get_db
from tools import (
    contar_defeitos, top_defeitos, defeitos_por_turno,
    gerar_grafico, gerar_tabela, gerar_kpi, gerar_dashboard,
)

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

client = anthropic.AsyncAnthropic()

# --- Mapa de tools disponíveis ---

TOOL_MAP = {
    "contar_defeitos": contar_defeitos,
    "top_defeitos": top_defeitos,
    "defeitos_por_turno": defeitos_por_turno,
    "gerar_grafico": gerar_grafico,
    "gerar_tabela": gerar_tabela,
    "gerar_kpi": gerar_kpi,
    "gerar_dashboard": gerar_dashboard,
}

RENDER_TOOLS = {"gerar_grafico", "gerar_tabela", "gerar_kpi", "gerar_dashboard"}

TOOL_DEFINITIONS = {
    "contar_defeitos": {
        "name": "contar_defeitos",
        "description": "Conta o número de defeitos registados. Pode filtrar por tipo de defeito específico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo_defeito": {
                    "type": "string",
                    "description": "Tipo de defeito para filtrar (ex: lixo, casca_laranja, falta_tinta, escorrido, gordura, descasque, crateras, outros). Se omitido, conta todos.",
                }
            },
        },
    },
    "top_defeitos": {
        "name": "top_defeitos",
        "description": "Devolve os N tipos de defeito mais frequentes com percentagens (análise de Pareto).",
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Número de tipos de defeito a devolver. Default: 5.",
                }
            },
        },
    },
    "defeitos_por_turno": {
        "name": "defeitos_por_turno",
        "description": "Conta defeitos agrupados por turno (manha, tarde, noite). Pode filtrar por turno específico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "turno": {
                    "type": "string",
                    "description": "Turno para filtrar (manha, tarde, noite). Se omitido, mostra todos os turnos.",
                }
            },
        },
    },
    "gerar_grafico": {
        "name": "gerar_grafico",
        "description": "Gera um gráfico visual no chat. Usa DEPOIS de consultar dados com as outras ferramentas. Tipos: bar, pie, line, doughnut.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {
                    "type": "string",
                    "enum": ["bar", "pie", "line", "doughnut"],
                    "description": "Tipo de gráfico.",
                },
                "titulo": {"type": "string", "description": "Título do gráfico."},
                "etiquetas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de etiquetas (eixo X ou fatias).",
                },
                "valores": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Lista de valores correspondentes às etiquetas.",
                },
                "dataset_label": {
                    "type": "string",
                    "description": "Legenda do dataset (ex: 'Contagem de defeitos').",
                },
            },
            "required": ["tipo", "titulo", "etiquetas", "valores"],
        },
    },
    "gerar_tabela": {
        "name": "gerar_tabela",
        "description": "Gera uma tabela formatada no chat. Usa DEPOIS de consultar dados.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Título da tabela."},
                "colunas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Nomes das colunas.",
                },
                "linhas": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "string"}},
                    "description": "Lista de linhas (cada linha é uma lista de valores string).",
                },
            },
            "required": ["titulo", "colunas", "linhas"],
        },
    },
    "gerar_kpi": {
        "name": "gerar_kpi",
        "description": "Gera um cartão KPI (métrica de destaque) no chat. Usa para realçar valores-chave.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Título do KPI (ex: 'Total de Defeitos')."},
                "valor": {"type": "string", "description": "Valor principal (ex: '200', '28.5%')."},
                "unidade": {"type": "string", "description": "Unidade (ex: 'defeitos', '%')."},
                "variacao": {"type": "string", "description": "Texto de variação opcional."},
            },
            "required": ["titulo", "valor"],
        },
    },
    "gerar_dashboard": {
        "name": "gerar_dashboard",
        "description": (
            "Gera um dashboard HTML completo acessível por link. Usa quando o utilizador pede um relatório, "
            "dashboard ou análise visual completa. O HTML é inserido num template que já inclui Chart.js e estilos base. "
            "Escreve apenas o conteúdo do body: divs, canvas para gráficos (com <script>new Chart(...)</script>), "
            "tabelas e KPIs. Classes CSS disponíveis: .kpi-card, .chart-container, .data-table, .dashboard-grid, .dashboard-row."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Título do dashboard."},
                "html": {
                    "type": "string",
                    "description": "Conteúdo HTML do body do dashboard. Pode incluir <canvas> + <script> para Chart.js, tabelas, KPIs, etc.",
                },
            },
            "required": ["titulo", "html"],
        },
    },
}

MAX_HISTORY = 20  # Últimas N mensagens a enviar ao modelo


async def process_message(user_id: int, conversa_id: int, user_message: str):
    """
    Processa uma mensagem do utilizador.
    Generator assíncrono que yield eventos SSE (JSON strings).
    """
    conn = get_db()

    # Validar conversa
    conversa = conn.execute(
        "SELECT * FROM conversas WHERE id = ? AND user_id = ?",
        (conversa_id, user_id),
    ).fetchone()
    if not conversa:
        conn.close()
        yield f'data: {json.dumps({"type": "error", "content": "Conversa não encontrada"})}\n\n'
        return

    # Carregar agente
    agente = conn.execute(
        "SELECT * FROM agentes WHERE id = ?", (conversa["agente_id"],)
    ).fetchone()

    # Guardar mensagem do user
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO mensagens (conversa_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (conversa_id, "user", user_message, now),
    )
    conn.commit()

    # Carregar histórico
    rows = conn.execute(
        "SELECT role, content FROM mensagens WHERE conversa_id = ? ORDER BY timestamp DESC LIMIT ?",
        (conversa_id, MAX_HISTORY),
    ).fetchall()
    rows = list(reversed(rows))

    messages = [{"role": r["role"], "content": r["content"]} for r in rows]

    # Tools permitidas para este agente
    allowed = json.loads(agente["tools"])
    tools = [TOOL_DEFINITIONS[t] for t in allowed if t in TOOL_DEFINITIONS]

    # Loop de tool use
    full_text = ""
    max_iterations = 8
    response = None

    try:
        for _ in range(max_iterations):
            # Stream da resposta
            async with client.messages.stream(
                model=MODEL,
                max_tokens=4096,
                system=agente["system_prompt"],
                messages=messages,
                tools=tools,
            ) as stream:
                async for text in stream.text_stream:
                    full_text += text
                    yield f'data: {json.dumps({"type": "text", "content": text})}\n\n'

                response = await stream.get_final_message()

            # Verificar se há tool_use
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            if not tool_uses:
                break

            # Adicionar resposta do assistente ao histórico (com content blocks)
            content_blocks = []
            for block in response.content:
                if block.type == "text":
                    content_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )
            messages.append({"role": "assistant", "content": content_blocks})

            # Executar tools e juntar resultados
            tool_results = []
            for tu in tool_uses:
                func = TOOL_MAP.get(tu.name)
                if func:
                    result = func(**tu.input)
                else:
                    result = {"error": f"Tool '{tu.name}' não encontrada"}

                if tu.name == "gerar_dashboard":
                    # Guardar dashboard na DB e devolver URL
                    dash_id = uuid.uuid4().hex[:12]
                    now_d = datetime.utcnow().isoformat()
                    conn.execute(
                        "INSERT INTO dashboards (id, user_id, titulo, html, created_at) VALUES (?, ?, ?, ?, ?)",
                        (dash_id, user_id, result["titulo"], result["html"], now_d),
                    )
                    conn.commit()
                    url = f"/dashboards/{dash_id}"
                    yield f'data: {json.dumps({"type": "dashboard", "url": url, "titulo": result["titulo"]}, ensure_ascii=False)}\n\n'
                    # Override result para o tool_result que volta ao Claude
                    result = {"status": "ok", "url": url}
                elif tu.name in RENDER_TOOLS:
                    widget_type = result.get("widget", "unknown")
                    yield f'data: {json.dumps({"type": widget_type, "data": result}, ensure_ascii=False)}\n\n'
                else:
                    yield f'data: {json.dumps({"type": "tool_use", "name": tu.name, "result": result}, ensure_ascii=False)}\n\n'

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            messages.append({"role": "user", "content": tool_results})
            full_text = ""  # Reset para a próxima iteração

    except anthropic.AuthenticationError:
        yield f'data: {json.dumps({"type": "error", "content": "API key inválida ou em falta. Define ANTHROPIC_API_KEY no ambiente."})}\n\n'
        conn.close()
        return
    except anthropic.APIError as e:
        yield f'data: {json.dumps({"type": "error", "content": f"Erro da API Anthropic: {e.message}"})}\n\n'
        conn.close()
        return
    except Exception as e:
        yield f'data: {json.dumps({"type": "error", "content": f"Erro inesperado: {str(e)}"})}\n\n'
        conn.close()
        return

    # Guardar resposta final do assistente
    if response:
        final_text = ""
        for block in response.content:
            if block.type == "text":
                final_text += block.text
        if final_text:
            now = datetime.utcnow().isoformat()
            conn.execute(
                "INSERT INTO mensagens (conversa_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (conversa_id, "assistant", final_text, now),
            )
            conn.commit()

    conn.close()
    yield f'data: {json.dumps({"type": "done"})}\n\n'
