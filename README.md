# QHub — Assistente de Qualidade Industrial com IA

PoC de uma webapp multi-utilizador com agentes Claude para controlo de qualidade em fábricas de pintura de peças plásticas para automóvel.

---

## O que é

O QHub permite que operadores e responsáveis de produção conversem com agentes de IA especializados que:

- Consultam dados reais de defeitos de pintura em tempo real
- Geram gráficos, tabelas e KPIs diretamente no chat via SSE streaming
- Criam dashboards HTML persistentes acessíveis por link
- Analisam ficheiros CSV/Excel carregados pelo utilizador
- Executam código Python ad-hoc para cálculos e análises
- Renderizam visualizações HTML/SVG inline (estilo artifacts do Claude.ai)

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | Python 3.11+ · FastAPI · Uvicorn |
| IA | Anthropic Claude (`claude-sonnet-4-20250514`) |
| Base de dados | SQLite |
| Autenticação | JWT (PyJWT) · bcrypt |
| Frontend | Vanilla JavaScript SPA · Chart.js 4.4.7 |
| Streaming | Server-Sent Events (SSE) |
| Dados | CSV estático (200 registos de defeitos) |

---

## Pré-requisitos

- Python 3.11+
- Conta Anthropic com `ANTHROPIC_API_KEY`

---

## Instalação

```bash
# 1. Clonar o repositório
git clone https://github.com/MAKE-IT-TECH/SandBox_Qhub_webpage.git
cd SandBox_Qhub_webpage

# 2. Criar e ativar ambiente virtual (recomendado)
python -m venv venv
source venv/bin/activate       # Linux/macOS
# venv\Scripts\activate        # Windows

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Configurar variáveis de ambiente
cp .env.example .env
# Editar .env e preencher ANTHROPIC_API_KEY
```

### `.env` mínimo

```env
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Arrancar o servidor

```bash
uvicorn server:app --reload --port 8000
```

Abrir em: **http://localhost:8000**

---

## Utilizadores demo

O seed é criado automaticamente na primeira execução (quando `qhub.db` não existe).

| Email | Password | Role | Agentes disponíveis |
|-------|----------|------|---------------------|
| `maria@demo.com` | `maria123` | operadora | Qualidade |
| `rui@demo.com` | `rui123` | responsavel | Qualidade, Análise |
| `admin@demo.com` | `admin123` | admin | Qualidade, Análise + painel admin |

---

## Estrutura de ficheiros

```
SandBox_Qhub_webpage/
├── server.py           # FastAPI — 20 endpoints REST + serve frontend
├── agent_engine.py     # Loop de orquestração Claude + SSE streaming
├── tools.py            # 8 tools Python (dados CSV + rendering + Python exec)
├── db.py               # Schema SQLite (6 tabelas) + seed demo
├── auth.py             # JWT + bcrypt
├── config.py           # Variáveis de ambiente
├── requirements.txt    # Dependências Python
├── .env.example        # Template de configuração
├── static/
│   └── index.html      # SPA completo (chat + admin + artifact renderer)
├── data/
│   └── defeitos.csv    # 200 registos de defeitos industriais
└── documentation/
    └── architecture.md # Diagramas Mermaid da arquitetura
```

---

## Funcionalidades

### Agentes e Roles

Cada utilizador tem acesso a um subconjunto de agentes configurados pelo admin:

- **Qualidade** — orientado ao operador de chão de fábrica. Identifica defeitos frequentes, gera alertas, visualizações rápidas.
- **Análise** — orientado ao responsável de produção. Análise comparativa por turno, tendências temporais, correlações material/defeito, execução Python ad-hoc.

### Tools disponíveis

| Tool | Agentes | O que faz |
|------|---------|-----------|
| `contar_defeitos` | Qualidade, Análise | Conta defeitos, opcionalmente por tipo |
| `top_defeitos` | Qualidade, Análise | Ranking Pareto com percentagens |
| `defeitos_por_turno` | Análise | Agrupamento por turno (manhã/tarde/noite) |
| `gerar_grafico` | Qualidade, Análise | Gráfico Chart.js inline no chat (bar/pie/line/doughnut) |
| `gerar_tabela` | Qualidade, Análise | Tabela formatada inline no chat |
| `gerar_kpi` | Qualidade, Análise | Card KPI inline no chat |
| `gerar_dashboard` | Qualidade, Análise | Dashboard HTML persistente com URL partilhável |
| `executar_python` | Análise | Executa código Python num subprocess isolado (timeout 30s) |

### Upload de ficheiros

O utilizador pode carregar ficheiros CSV ou Excel diretamente no chat (botão 📎). O conteúdo é injetado como contexto na conversa — o agente "vê" os dados e pode responder com análises, gráficos, etc.

### Artifact Renderer

Quando o Claude gera um bloco de código ` ```html ` ou ` ```svg ` na sua resposta, o frontend renderiza-o automaticamente como um iframe sandboxado inline, com toggle entre **Render** e **Código** e botão **↗ Abrir** em nova aba.

### Admin

Utilizadores com role `admin` têm acesso ao painel de administração para:
- Gerir agentes (nome, system prompt, tools atribuídas)
- Gerir utilizadores (criar, editar, apagar, atribuir agentes)
- Ver todas as tools disponíveis

---

## API REST

### Autenticação

```
POST /auth/login
Body: { "email": "...", "password": "..." }
→ { "token": "...", "nome": "...", "role": "..." }
```

Todos os endpoints protegidos requerem o header:
```
Authorization: Bearer <token>
```

### Endpoints principais

| Método | Endpoint | Acesso | Descrição |
|--------|----------|--------|-----------|
| `POST` | `/auth/login` | público | Login → JWT |
| `GET` | `/agentes` | user | Listar agentes do utilizador |
| `POST` | `/conversas` | user | Nova conversa |
| `GET` | `/conversas` | user | Listar conversas |
| `GET` | `/conversas/{id}/mensagens` | user | Histórico de mensagens |
| `POST` | `/conversas/{id}/mensagens` | user | Enviar mensagem → SSE stream |
| `POST` | `/conversas/{id}/upload` | user | Upload CSV/Excel |
| `GET` | `/dashboards/{id}` | público | Ver dashboard gerado |
| `GET/POST/PUT/DELETE` | `/admin/agentes` | admin | CRUD agentes |
| `GET/POST/PUT/DELETE` | `/admin/users` | admin | CRUD utilizadores |
| `GET` | `/admin/tools` | admin | Listar tools disponíveis |

### SSE — Tipos de eventos

O endpoint `POST /conversas/{id}/mensagens` devolve um stream SSE com os seguintes tipos de evento:

```jsonc
{"type": "text", "content": "..."}          // Chunk de texto em stream
{"type": "chart", "data": {...}}             // Widget gráfico
{"type": "table", "data": {...}}             // Widget tabela
{"type": "kpi", "data": {...}}               // Widget KPI
{"type": "dashboard", "url": "...", "titulo": "..."}  // Link para dashboard
{"type": "tool_use", "name": "...", "result": {...}}  // Resultado de tool
{"type": "error", "content": "..."}         // Erro
{"type": "done"}                             // Fim do stream
```

---

## Dados demo

`data/defeitos.csv` — 200 registos de defeitos de pintura (Fevereiro 2026):

| Campo | Valores |
|-------|---------|
| `turno` | manha, tarde, noite |
| `operador` | Julia, Margareta, Pedro, Carlos |
| `tipo_defeito` | lixo (~30%), falta_tinta, casca_laranja, gordura, descasque, escorrido, crateras, outros |
| `material` | ABS_Cinza, PP_Negro, PP_Vermelho, PA_Branco |
| `rack` | R10–R15 |

---

## Configuração avançada

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `ANTHROPIC_API_KEY` | — | **Obrigatória** |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Modelo Claude a usar |
| `JWT_SECRET` | `qhub-poc-secret-mude-em-producao` | Segredo JWT — **mudar em produção** |
| `JWT_EXPIRY_HOURS` | `8` | Duração do token em horas |

---

## Limitações (PoC)

- **SQLite** — não escala para múltiplos utilizadores simultâneos em produção
- **CSV estático** — os dados de defeitos não são atualizados em tempo real
- **Sem HTTPS** — usar um reverse proxy (nginx/caddy) em produção
- **JWT_SECRET inseguro** por defeito — obrigatório alterar em produção
- **`executar_python`** — sandbox por string-matching simples, suficiente para uso interno
- **Sem testes automatizados**
- **Sem Docker** — deployment manual
- **Artifacts em histórico** — ao reabrir uma conversa, blocos `html` antigos aparecem como texto

---

## Licença

Projeto interno MAKE IT — PoC não licenciado para distribuição.
