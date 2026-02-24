# Tool System — How Claude Accesses Tools

## Overview

Claude does not execute code directly. Instead, the system follows a **request → execute → return** pattern: Claude requests a tool call, the backend executes the corresponding Python function, and the result is sent back to Claude as context for its next response.

## The Three Layers

### 1. Tool Definitions (JSON Schemas)

In `agent_engine.py`, the `TOOL_DEFINITIONS` dictionary describes each tool using the format expected by the Anthropic API — a name, a natural-language description, and a JSON Schema for the input parameters:

```python
TOOL_DEFINITIONS = {
    "contar_defeitos": {
        "name": "contar_defeitos",
        "description": "Conta o número de defeitos registados...",
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo_defeito": {
                    "type": "string",
                    "description": "Tipo de defeito para filtrar..."
                }
            }
        }
    },
    # ... more tools
}
```

Claude receives **only** these schemas — not the Python source code. It uses the `description` and `input_schema` to decide **when** to call a tool and **what arguments** to pass.

### 2. Per-Agent Filtering

Not all tools are sent to Claude on every request. Each agent in the database has a `tools` column containing a JSON array of allowed tool names (e.g. `["contar_defeitos", "gerar_grafico"]`).

Before calling the API, the engine filters the definitions:

```python
allowed = json.loads(agente["tools"])
tools = [TOOL_DEFINITIONS[t] for t in allowed if t in TOOL_DEFINITIONS]
```

This means the "Qualidade" agent might see 5 tools while the "Análise" agent sees 7 — each agent only knows about the tools assigned to it via the admin panel.

### 3. Execution (The Agentic Loop)

The filtered schemas are passed in the `tools` parameter of the API call:

```python
async with client.messages.stream(
    model=MODEL,
    system=agente["system_prompt"],
    messages=messages,
    tools=tools,
) as stream:
```

When Claude decides to use a tool, its response includes a `tool_use` block with the tool name and arguments. The engine dispatches the call through `TOOL_MAP`, which maps tool names (strings) to Python functions in `tools.py`:

```python
TOOL_MAP = {
    "contar_defeitos": contar_defeitos,
    "top_defeitos": top_defeitos,
    "defeitos_por_turno": defeitos_por_turno,
    "gerar_grafico": gerar_grafico,
    "gerar_tabela": gerar_tabela,
    "gerar_kpi": gerar_kpi,
    "gerar_dashboard": gerar_dashboard,
}

# Dispatch
func = TOOL_MAP.get(tu.name)
result = func(**tu.input)
```

The result is serialized to JSON and sent back to Claude as a `tool_result` message. The loop then continues — Claude can call another tool or produce a final text response.

## Iteration Limit

The loop runs for a maximum of **8 iterations** (`max_iterations = 8`). This is a safety guard to prevent infinite loops and uncontrolled API costs. In practice most interactions use 1–3 iterations. If the limit is reached the loop exits, the last response is saved, and a `done` event is sent to the browser.

## End-to-End Flow

```
User sends message
        │
        ▼
Engine loads agent config (system_prompt + allowed tools)
Engine loads conversation history (last 20 messages)
        │
        ▼
┌─────────────────────────────────────────────────┐
│  Loop (up to 8 iterations)                      │
│                                                 │
│  1. Call Claude API with messages + tool schemas │
│  2. Stream text chunks to browser via SSE       │
│  3. If response contains tool_use blocks:       │
│     a. Execute each tool via TOOL_MAP           │
│     b. Send widget/data events to browser       │
│     c. Append tool_results to messages          │
│     d. Continue loop                            │
│  4. If no tool_use → break                      │
└─────────────────────────────────────────────────┘
        │
        ▼
Save final assistant message to database
Send "done" event to browser
```

## Tool Categories

| Category    | Tools                                            | Behavior                                                   |
|-------------|--------------------------------------------------|------------------------------------------------------------|
| Data query  | `contar_defeitos`, `top_defeitos`, `defeitos_por_turno` | Read `defeitos.csv`, return JSON data to Claude       |
| Render      | `gerar_grafico`, `gerar_tabela`, `gerar_kpi`     | Pass-through: return widget config, sent to browser via SSE |
| Dashboard   | `gerar_dashboard`                                | HTML saved to database, URL returned to Claude and browser  |

Data tools give Claude information to reason about. Render tools let Claude produce visual output in the chat. The dashboard tool creates a persistent, shareable page.
