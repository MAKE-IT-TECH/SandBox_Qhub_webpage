# Plano PoC — QHub Web App Multi-User

## Contexto

Prova de conceito para demonstrar que a MAKE IT consegue entregar uma app web onde varios utilizadores acedem a agentes de IA especializados. Hoje o PoC funciona no Claude Desktop com MCP — nao e escalavel nem apresentavel a um cliente. O objectivo e montar algo funcional minimo que demonstre: multi-user, agentes especializados por perfil, tools que acedem a dados, e streaming de respostas.

## Stack

- **Backend**: Python + FastAPI
- **Frontend**: HTML + JS (vanilla, sem framework)
- **LLM**: Anthropic API (Claude Sonnet)
- **DB da app**: SQLite (users, agentes, conversas)
- **Dados de demo**: CSV simples com defeitos de pintura
- **Deploy**: Local (`python server.py`)

## Estrutura do Projecto

```
qhub-web/
├── server.py              # FastAPI — endpoints API + serve frontend
├── agent_engine.py        # Logica de agentes: system prompts, tool dispatch, streaming
├── tools.py               # Funcoes Python que consultam o CSV
├── db.py                  # Setup SQLite + helpers (users, agentes, conversas)
├── auth.py                # Login simples (JWT)
├── requirements.txt       # fastapi, uvicorn, anthropic, pyjwt
├── static/
│   └── index.html         # Frontend — pagina de chat
└── data/
    └── defeitos.csv       # CSV com dados de exemplo de defeitos
```

## Fases de Execucao

### Fase 1 — Dados de demo (data/defeitos.csv)

Um CSV simples com colunas:

```
id,data,turno,operador,tipo_defeito,material,rack,posicao
1,2026-02-01,manha,Julia,lixo,PP_Negro,R12,3
2,2026-02-01,manha,Julia,casca_laranja,PP_Negro,R12,5
3,2026-02-01,tarde,Margareta,falta_tinta,ABS_Cinza,R14,1
...
```

- ~200 linhas (suficiente para demonstrar)
- 6-8 tipos de defeito (lixo, casca_laranja, falta_tinta, escorrido, gordura, descasque, outros)
- 3 turnos (manha, tarde, noite)
- 3-4 operadores
- Distribuicao realista (lixo ~30%, casca_laranja ~15%, etc.)

### Fase 2 — Tools (tools.py)

Script Python simples que le o CSV com o modulo csv (sem pandas) e responde a consultas:

- `contar_defeitos(tipo_defeito=None)` — conta defeitos, opcionalmente filtrado por tipo
- `top_defeitos(n=5)` — devolve os N defeitos mais frequentes (Pareto)
- `defeitos_por_turno(turno=None)` — conta defeitos por turno

Cada funcao le o CSV, faz a contagem, e devolve um dicionario simples. Nada mais.

### Fase 3 — DB da app + Auth (db.py + auth.py)

SQLite para gestao da app:

- Tabela `users`: id, nome, email, password_hash, role
- Tabela `agentes`: id, nome, system_prompt, tools (JSON)
- Tabela `user_agentes`: user_id, agente_id
- Tabela `conversas`: id, user_id, agente_id, created_at
- Tabela `mensagens`: id, conversa_id, role, content, timestamp

Auth: login com email+password, devolve JWT.

Seed com 2 users de demo:
- **Maria** (operadora) — acesso ao agente "Qualidade"
- **Rui** (responsavel) — acesso a "Qualidade" + "Analise"

Seed com 2 agentes:
- **Qualidade** — system prompt focado em alertas e defeitos frequentes. Tools: contar_defeitos, top_defeitos
- **Analise** — system prompt focado em padroes e comparacoes entre turnos. Tools: todas

### Fase 4 — Agent Engine (agent_engine.py)

O core da app. Para cada mensagem do user:

1. Carrega config do agente (system prompt + tools permitidas)
2. Carrega historico da conversa (ultimas N mensagens)
3. Chama API do Claude com as tools definidas
4. Se Claude pede tool_use → executa funcao de tools.py → devolve resultado ao Claude
5. Loop ate Claude dar resposta final
6. Guarda mensagens na DB
7. Devolve resposta em streaming via SSE

### Fase 5 — API (server.py)

Endpoints:

- `POST /auth/login` — login, devolve JWT
- `GET /agentes` — lista agentes do user autenticado
- `POST /conversas` — cria nova conversa
- `POST /conversas/{id}/mensagens` — envia mensagem, resposta em SSE streaming

### Fase 6 — Frontend (static/index.html)

Pagina unica:

- Login (email + password)
- Sidebar: agentes disponiveis
- Area central: chat com streaming
- ~200 linhas HTML/CSS/JS

### Fase 7 — Testar

1. Arrancar: `uvicorn server:app --reload`
2. Abrir browser em http://localhost:8000
3. Login como Maria — ve so agente "Qualidade"
4. Perguntar "Quais os defeitos mais frequentes?" — agente chama top_defeitos() e responde
5. Abrir outra janela, login como Rui — ve "Qualidade" + "Analise"
6. Perguntar ao agente Analise "Compara os defeitos entre turnos" — chama defeitos_por_turno()
7. Verificar que os contextos sao independentes

## O que este PoC demonstra

1. **Multi-user** — 2 utilizadores com sessoes independentes
2. **Agentes especializados** — prompts e tools diferentes por perfil
3. **Tool use** — o agente consulta o CSV e responde com base nos dados
4. **Streaming** — respostas em tempo real
5. **Web-based** — browser, sem instalar nada

## O que NAO faz (e esta ok)

- Dados simulados num CSV, nao liga a DB real
- Sem HTTPS
- Sem gestao de passwords, registo, etc.
- Sem controlo de custos de tokens
- Sem deploy cloud

## Dependencias

```
fastapi
uvicorn[standard]
anthropic
pyjwt
bcrypt
```

## Evolucao pos-PoC

Se o PoC validar o conceito:
- Substituir CSV por ligacao a DB real da Stratis (read-only)
- Adicionar mais tools (correlacoes, tendencias, alertas)
- Deploy em Docker na rede do cliente
- Adicionar mais perfis de utilizador
- HTTPS + auth mais robusta
- Controlo de custos (rate limiting por user)
