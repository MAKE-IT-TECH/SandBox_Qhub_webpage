# QHub — Industrial Quality Control PoC

A multi-user web application that uses claude API.
## Architecture

```
Browser (SPA)  ──HTTP/SSE──▶  FastAPI Backend  ──▶  Anthropic Claude API
                               ├── auth.py (JWT)
                               ├── agent_engine.py (tool loop)
                               └── tools.py (data queries)
                                      │
                                      ▼
                              SQLite + defeitos.csv
```

- **Backend:** FastAPI + Uvicorn, SQLite, JWT authentication (bcrypt)
- **Frontend:** Vanilla HTML/JS single-page app, Chart.js for visualizations
- **AI:** Claude Sonnet via Anthropic API with agentic tool use loop (up to 8 iterations)
- **Streaming:** Server-Sent Events (SSE) for real-time responses

## Features

- **Role-based access** — `admin`, `operadora`, `responsavel`
- **Specialized agents** — each with configurable system prompts and tool permissions
- **Data query tools** — count defects, Pareto analysis, shift breakdowns
- **Rich visualizations** — charts (bar, pie, line, doughnut), tables, KPI cards
- **Dashboard generation** — full HTML dashboards saved and shareable via URL
- **Admin panel** — manage agents, users, and tool assignments

## Quick Start

### Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)

### Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set your API key
export ANTHROPIC_API_KEY="your-key-here"
```

### Run

```bash
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000

### Demo Accounts

| Email             | Password  | Role        | Access                        |
|-------------------|-----------|-------------|-------------------------------|
| maria@demo.com    | maria123  | operadora   | Qualidade agent               |
| rui@demo.com      | rui123    | responsavel | Qualidade + Análise agents    |
| admin@demo.com    | admin123  | admin       | All agents + admin panel      |

## Project Structure

```
├── server.py              # FastAPI app, REST API, SSE streaming, admin endpoints
├── agent_engine.py        # Claude API integration, tool use loop, streaming
├── tools.py               # Data query and visualization tool functions
├── db.py                  # SQLite schema, initialization, seed data
├── auth.py                # JWT authentication and authorization
├── requirements.txt       # Python dependencies
├── static/
│   └── index.html         # Single-page frontend application
├── data/
│   └── defeitos.csv       # Sample paint defect data (200 rows)
└── documentation/
    └── architecture.md    # Detailed architecture diagrams (Mermaid)
```

## API Endpoints

| Method | Endpoint                           | Auth    | Description                      |
|--------|------------------------------------|---------|----------------------------------|
| POST   | `/auth/login`                      | Public  | Authenticate, returns JWT        |
| GET    | `/dashboards/{id}`                 | Public  | View generated dashboard         |
| GET    | `/agentes`                         | JWT     | List agents for current user     |
| POST   | `/conversas`                       | JWT     | Create conversation              |
| GET    | `/conversas`                       | JWT     | List user's conversations        |
| GET    | `/conversas/{id}/mensagens`        | JWT     | Get conversation messages        |
| POST   | `/conversas/{id}/mensagens`        | JWT     | Send message (SSE stream)        |
| GET    | `/admin/agentes`                   | Admin   | List all agents                  |
| POST   | `/admin/agentes`                   | Admin   | Create agent                     |
| PUT    | `/admin/agentes/{id}`              | Admin   | Update agent                     |
| DELETE | `/admin/agentes/{id}`              | Admin   | Delete agent                     |
| GET    | `/admin/tools`                     | Admin   | List available tools             |
| GET    | `/admin/users`                     | Admin   | List all users                   |
| POST   | `/admin/users`                     | Admin   | Create user                      |
| PUT    | `/admin/users/{id}`                | Admin   | Update user                      |
| DELETE | `/admin/users/{id}`                | Admin   | Delete user                      |
| GET    | `/admin/users/{id}/agentes`        | Admin   | Get user's agent assignments     |
| PUT    | `/admin/users/{id}/agentes`        | Admin   | Set user's agent assignments     |

## Available Tools

**Data query:**
- `contar_defeitos` — Count defects, optionally filtered by type
- `top_defeitos` — Pareto ranking of most frequent defects
- `defeitos_por_turno` — Defect breakdown by shift (morning/afternoon/night)

**Visualization:**
- `gerar_grafico` — Generate chart (bar, pie, line, doughnut)
- `gerar_tabela` — Generate formatted data table
- `gerar_kpi` — Generate KPI metric card
- `gerar_dashboard` — Generate and persist a full HTML dashboard

## Configuration

| Environment Variable | Default                              | Description            |
|----------------------|--------------------------------------|------------------------|
| `ANTHROPIC_API_KEY`  | *(required)*                         | Anthropic API key      |
| `ANTHROPIC_MODEL`    | `claude-sonnet-4-20250514`           | Claude model to use    |
| `JWT_SECRET`         | `qhub-poc-secret-mude-em-producao`   | JWT signing secret     |

## Sample Data

The file `data/defeitos.csv` contains 200 rows of simulated paint defect records with the following fields:

| Column        | Description                                              |
|---------------|----------------------------------------------------------|
| id            | Defect ID                                                |
| data          | Date (YYYY-MM-DD)                                       |
| turno         | Shift — manha, tarde, noite                              |
| operador      | Operator — Julia, Margareta, Pedro, Carlos               |
| tipo_defeito  | Defect type — lixo, casca_laranja, falta_tinta, etc.     |
| material      | Material — PP_Negro, ABS_Cinza, PA_Branco, PP_Vermelho   |
| rack          | Rack location (R10–R15)                                  |
| posicao       | Position in rack (1–8)                                   |
