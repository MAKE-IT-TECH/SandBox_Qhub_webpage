# QHub — Guia Técnico de Utilização

Este documento explica em detalhe o que acontece internamente em cada operação do sistema: como a ligação à API Claude funciona, o que é enviado em cada mensagem, como o upload de ficheiros é processado, e como o loop de conversa contínua é mantido.

---

## Índice

1. [Visão geral do fluxo](#1-visão-geral-do-fluxo)
2. [Ligação à API Claude (Anthropic)](#2-ligação-à-api-claude-anthropic)
3. [O que é enviado ao Claude em cada mensagem](#3-o-que-é-enviado-ao-claude-em-cada-mensagem)
4. [O loop de tool use — como o Claude usa ferramentas](#4-o-loop-de-tool-use--como-o-claude-usa-ferramentas)
5. [Streaming SSE — como a resposta chega ao browser](#5-streaming-sse--como-a-resposta-chega-ao-browser)
6. [Upload de ficheiros CSV/Excel](#6-upload-de-ficheiros-csvexcel)
7. [Conversa contínua — contexto e histórico](#7-conversa-contínua--contexto-e-histórico)
13. [Custos de tokens — o que gasta o quê](#13-custos-de-tokens--o-que-gasta-o-quê)
8. [Artifact Renderer — HTML/SVG inline](#8-artifact-renderer--htmlsvg-inline)
9. [Dashboards persistentes](#9-dashboards-persistentes)
10. [Execução de código Python](#10-execução-de-código-python)
11. [Autenticação e sessões](#11-autenticação-e-sessões)
12. [Limites e comportamentos de fronteira](#12-limites-e-comportamentos-de-fronteira)

---

## 1. Visão geral do fluxo

```
Utilizador (browser)
    │
    │  POST /conversas/{id}/mensagens
    │  { "content": "qual é o defeito mais frequente?" }
    ▼
FastAPI (server.py)
    │
    │  StreamingResponse → SSE
    ▼
agent_engine.py → process_message()
    │
    ├── Carrega system_prompt + tools do agente (SQLite)
    ├── Carrega histórico de mensagens (SQLite, máx 20)
    │
    │  POST api.anthropic.com/v1/messages  (streaming)
    ▼
Claude API
    │
    ├── Responde com texto (chunks em stream)
    └── Ou responde com tool_use → executa tool → devolve resultado → chama Claude de novo
    │
    ▼
SSE events → browser → renderiza texto, gráficos, tabelas, KPIs, dashboards
```

---

## 2. Ligação à API Claude (Anthropic)

### Cliente

```python
# agent_engine.py
client = anthropic.AsyncAnthropic()
```

O SDK Anthropic lê automaticamente a variável `ANTHROPIC_API_KEY` do ambiente. O cliente é assíncrono (`AsyncAnthropic`) para compatibilidade com FastAPI/Uvicorn async.

### Modelo utilizado

Configurado em `.env`:
```
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

Se não definido, o padrão é `claude-sonnet-4-20250514` (ver `config.py`).

### Chamada à API

Em cada iteração do loop, é feita uma chamada com streaming:

```python
async with client.messages.stream(
    model=MODEL,                  # ex: "claude-sonnet-4-20250514"
    max_tokens=4096,              # máximo de tokens na resposta
    system=effective_prompt,      # system prompt do agente + artifact_hint
    messages=messages,            # histórico completo da conversa
    tools=tools,                  # definições JSON das tools disponíveis
) as stream:
    async for text in stream.text_stream:
        yield f'data: {json.dumps({"type": "text", "content": text})}\n\n'
    response = await stream.get_final_message()
```

O `stream.text_stream` emite chunks de texto à medida que o Claude os gera. `get_final_message()` aguarda o fim completo da resposta para inspecionar os `tool_use` blocks.

---

## 3. O que é enviado ao Claude em cada mensagem

Cada chamada à API contém **4 componentes**:

### 3.1 System prompt

O `system` é composto por:

```
[system_prompt do agente (definido no DB)]
+
[artifact_hint injetado automaticamente pelo agent_engine]
```

**Exemplo para o agente "Qualidade":**
```
És um assistente de qualidade industrial numa fábrica de pintura de peças plásticas
para automóveis. O teu papel é ajudar operadores a identificar e reportar defeitos...
[instruções de visualização, dashboards]

ARTIFACTS INLINE: Quando precisares de mostrar uma visualização ou código HTML/SVG
diretamente no chat (não como dashboard persistente), produz um bloco de código
markdown com a linguagem 'html' ou 'svg'...
```

O system prompt **nunca muda** durante a conversa — é sempre o mesmo para todas as mensagens da mesma conversa.

### 3.2 Histórico de mensagens (`messages`)

É a lista das últimas **20 mensagens** da conversa (incluindo a mensagem atual), ordenadas do mais antigo para o mais recente:

```json
[
  {"role": "user",      "content": "qual o defeito mais frequente?"},
  {"role": "assistant", "content": "O defeito mais frequente é 'lixo' com 62 ocorrências..."},
  {"role": "user",      "content": "e por turno?"},
  {"role": "assistant", "content": [
    {"type": "text",     "text": "Vou verificar por turno..."},
    {"type": "tool_use", "id": "tu_abc", "name": "defeitos_por_turno", "input": {}}
  ]},
  {"role": "user",      "content": [
    {"type": "tool_result", "tool_use_id": "tu_abc", "content": "{\"por_turno\": {...}}"}
  ]},
  {"role": "assistant", "content": "No turno da manhã registaram-se 78 defeitos..."},
  {"role": "user",      "content": "mostra num gráfico"}
]
```

> **Nota importante:** Quando há tool use, o formato das mensagens muda. A resposta do assistant inclui blocos `tool_use`, e a mensagem seguinte do "user" inclui os `tool_result`. O Claude precisa desta estrutura para saber o que as tools devolveram.

### 3.3 Definições das tools (`tools`)

Apenas as tools atribuídas ao agente são enviadas. Cada tool tem:
- `name` — identificador
- `description` — instrução em linguagem natural para o Claude perceber quando usar
- `input_schema` — JSON Schema que define os parâmetros aceites

**Exemplo completo enviado para o agente Qualidade:**
```json
[
  {
    "name": "contar_defeitos",
    "description": "Conta o número de defeitos registados. Pode filtrar por tipo...",
    "input_schema": {
      "type": "object",
      "properties": {
        "tipo_defeito": {"type": "string", "description": "..."}
      }
    }
  },
  {
    "name": "top_defeitos",
    "description": "Devolve os N tipos de defeito mais frequentes com percentagens...",
    "input_schema": {
      "type": "object",
      "properties": {
        "n": {"type": "integer", "description": "..."}
      }
    }
  },
  ... (gerar_grafico, gerar_tabela, gerar_kpi, gerar_dashboard)
]
```

O agente **Análise** recebe as mesmas mais `defeitos_por_turno` e `executar_python`.

### 3.4 max_tokens

Fixo em `4096`. Suficiente para respostas longas com dashboards HTML complexos.

---

## 4. O loop de tool use — como o Claude usa ferramentas

O Claude não acede diretamente à base de dados nem ao CSV. Em vez disso, **pede ao servidor** para executar uma tool. O servidor executa e devolve o resultado ao Claude, que usa essa informação para responder.

### Diagrama do loop

```
Iteração 1:
  Claude recebe: [histórico + mensagem do user]
  Claude responde: text_block("Vou verificar...") + tool_use("contar_defeitos", {})

  Servidor:
    → executa contar_defeitos() → lê defeitos.csv → {"total": 200, "por_tipo": {...}}
    → guarda no histórico: assistant=[text_block, tool_use_block]
    → guarda no histórico: user=[tool_result_block com o resultado JSON]

Iteração 2:
  Claude recebe: [histórico actualizado com resultado da tool]
  Claude responde: text_block("Os 200 defeitos dividem-se assim: ...")
                   + tool_use("gerar_grafico", {"tipo": "pie", "titulo": "...", ...})

  Servidor:
    → executa gerar_grafico() → devolve {"widget": "chart", ...}
    → emite SSE: {"type": "chart", "data": {...}}  ← browser renderiza gráfico
    → guarda tool_result no histórico

Iteração 3:
  Claude recebe: [histórico com ambos os resultados]
  Claude responde: text_block("Como pode ver no gráfico acima...")
                   (sem tool_use → loop termina)
```

### Número máximo de iterações

```python
max_iterations = 8  # agent_engine.py
```

Se o Claude precisar de mais de 8 chamadas encadeadas (ex: para um dashboard muito complexo), o loop pára na 8ª iteração e guarda o que existir até aí.

### O Claude "vê" os dados reais

O CSV nunca é enviado ao Claude na totalidade. O Claude "vê" apenas os resultados das tools que pediu — por exemplo:

```json
{
  "total": 200,
  "por_tipo": {
    "lixo": 62,
    "falta_tinta": 31,
    "casca_laranja": 27,
    "gordura": 24,
    "descasque": 21,
    "escorrido": 19,
    "crateras": 12,
    "outros": 4
  }
}
```

Quando um ficheiro é carregado via upload (ver secção 6), aí sim o conteúdo do CSV é enviado directamente ao Claude como texto.

---

## 5. Streaming SSE — como a resposta chega ao browser

O endpoint `POST /conversas/{id}/mensagens` devolve um `StreamingResponse` com `media_type="text/event-stream"`. O browser lê o stream linha a linha.

### Formato de cada evento

```
data: {"type": "text", "content": "O defeito"}\n\n
data: {"type": "text", "content": " mais frequente"}\n\n
data: {"type": "text", "content": " é lixo."}\n\n
data: {"type": "tool_use", "name": "gerar_grafico", "result": {...}}\n\n
data: {"type": "chart", "data": {"widget": "chart", "tipo": "pie", ...}}\n\n
data: {"type": "done"}\n\n
```

### Tipos de eventos e o que o browser faz

| Tipo | Origem | Ação no browser |
|------|--------|-----------------|
| `text` | Chunk de texto do Claude em stream | Appended ao elemento `div.msg.assistant` em tempo real |
| `tool_use` | Tool de dados executada (contar, top, turno, executar_python) | Mostra indicador `🔧 nome_da_tool()` |
| `chart` | `gerar_grafico` executada | Cria `<canvas>` e instancia `new Chart(...)` |
| `table` | `gerar_tabela` executada | Cria tabela HTML estilizada |
| `kpi` | `gerar_kpi` executada | Cria card KPI com gradiente |
| `dashboard` | `gerar_dashboard` executada + guardada no DB | Cria iframe apontando para `/dashboards/{id}` |
| `error` | Erro na API ou no servidor | Mostra mensagem de erro a vermelho |
| `done` | Fim de toda a geração | — (o loop JS termina) |

### Parsing no frontend

O browser não usa a API `EventSource` nativa (que não suporta `POST`). Em vez disso, lê o `ReadableStream` manualmente:

```javascript
// index.html — sendMsg()
const reader = res.body.getReader();
const decoder = new TextDecoder();
let buffer = '';
let accText = '';

while (true) {
    const {value, done} = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, {stream: true});
    const lines = buffer.split('\n');
    buffer = lines.pop(); // guarda linha incompleta para a próxima iteração

    for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const evt = JSON.parse(line.slice(6));
        // despacha por evt.type ...
    }
}

postProcessArtifacts(assistantEl, accText); // pós-processa artifacts HTML/SVG
```

---

## 6. Upload de ficheiros CSV/Excel

### O que acontece passo a passo

**No browser:**
1. Utilizador clica no botão 📎 → abre file picker
2. Após seleção, `uploadFile()` é chamado automaticamente (`onchange`)
3. Mostra indicador `📎 A processar ficheiro.csv...`
4. Envia `POST /conversas/{id}/upload` com `multipart/form-data`

**No servidor (`server.py`):**

```
1. Valida extensão (.csv ou .xlsx) → 400 se inválido
2. Valida que a conversa pertence ao utilizador autenticado → 404 se não
3. Lê bytes do ficheiro
4. Parseia com pandas:
   - CSV:   pd.read_csv(io.BytesIO(content))
   - Excel: pd.read_excel(io.BytesIO(content), engine="openpyxl")
5. Extrai:
   - preview_csv  = primeiras 10 linhas em CSV
   - dados_csv    = primeiras 100 linhas em CSV
   - stats_str    = df.describe().to_string()  (min/max/mean/std de colunas numéricas)
   - cat_info     = top 5 valores das primeiras 5 colunas categóricas
6. Formata tudo como uma mensagem de texto
7. Guarda na tabela `mensagens` com role="user"
8. Retorna { mensagem_id, resumo }
```

### Exatamente o que é guardado e enviado ao Claude

A mensagem injetada tem este formato (exemplo com `defeitos.csv`):

```
[FICHEIRO CARREGADO: defeitos.csv]
Colunas: id, data, turno, operador, tipo_defeito, material, rack, posicao
Registos: 200

Primeiras 10 linhas:
id,data,turno,operador,tipo_defeito,material,rack,posicao
1,2026-02-11,manha,Julia,gordura,ABS_Cinza,R11,3
2,2026-02-12,manha,Julia,escorrido,PP_Negro,R10,2
...

Estatísticas numéricas:
          id       posicao
count  200.0    200.000000
mean   100.5      4.590000
std     57.8      2.305...
min      1.0      1.000000
...

Distribuição das colunas categóricas (top 5):
  turno: {'manha': 73, 'tarde': 68, 'noite': 59}
  operador: {'Julia': 55, 'Carlos': 52, 'Pedro': 49, 'Margareta': 44}
  tipo_defeito: {'lixo': 62, 'falta_tinta': 31, 'casca_laranja': 27, 'gordura': 24, 'descasque': 21}
  material: {'ABS_Cinza': 58, 'PP_Negro': 54, 'PP_Vermelho': 47, 'PA_Branco': 41}
  rack: {'R12': 38, 'R11': 37, 'R13': 36, 'R10': 33, 'R14': 29}

Dados completos (primeiras 100 linhas):
id,data,turno,operador,tipo_defeito,...
1,2026-02-11,...
...
```

Esta mensagem fica guardada no SQLite com `role="user"`. Na próxima chamada ao Claude, ele vê esta mensagem no histórico como se o utilizador tivesse "colado" o conteúdo.

### O que acontece depois

O upload **não dispara** uma resposta do Claude automaticamente. A mensagem fica guardada, e o utilizador é convidado a escrever a sua pergunta. Quando o faz, o Claude já vê os dados no histórico.

**Exemplo de fluxo completo:**
```
[upload defeitos.csv]  → mensagem "user" guardada no DB
[utilizador escreve: "que padrões vês nestes dados?"]
  → Claude recebe: [mensagem do ficheiro + pergunta do utilizador]
  → Claude "vê" o CSV e responde com análise
```

---

## 7. Conversa contínua — contexto e histórico

### Como o contexto é mantido

O QHub **não tem memória em RAM** entre requests. Cada pedido `POST /conversas/{id}/mensagens` é independente. O contexto é reconstituído de raiz em cada pedido:

```python
# agent_engine.py — process_message()

rows = conn.execute(
    "SELECT role, content FROM mensagens WHERE conversa_id = ? ORDER BY timestamp DESC LIMIT ?",
    (conversa_id, MAX_HISTORY),  # MAX_HISTORY = 20
).fetchall()
rows = list(reversed(rows))  # reordena para cronológico
messages = [{"role": r["role"], "content": r["content"]} for r in rows]
```

### O que conta para o limite de 20 mensagens

Cada turno (user + assistant) = 2 mensagens. Portanto, 20 mensagens = **10 trocas** user/assistant.

Se a conversa for mais longa, as mensagens mais antigas são descartadas do contexto enviado ao Claude. Ficam guardadas no SQLite (histórico completo), mas o Claude não as "vê" nas chamadas subsequentes.

### Mensagens especiais no histórico

Quando há tool use, a conversa no DB contém mensagens "normais" de texto, mas na chamada ao Claude, o `messages` array pode conter blocos estruturados:

```python
# Mensagem do assistente com tool use (guardada em memória durante o loop, não no DB)
{"role": "assistant", "content": [
    {"type": "text", "text": "Vou verificar..."},
    {"type": "tool_use", "id": "tu_xyz", "name": "top_defeitos", "input": {"n": 5}}
]}

# Resultado da tool (guardado em memória durante o loop, não no DB)
{"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "tu_xyz", "content": "{\"top\": [...]}"}
]}
```

**Importante:** Os blocos de tool use e tool result existem apenas **dentro do loop `process_message`** e não são guardados no SQLite. O que é guardado no DB é apenas o texto final da resposta do assistant.

Quando a conversa é reaberta, o histórico carregado contém apenas mensagens de texto — os tool results intermédios são perdidos. O Claude não terá contexto de "que ferramentas usou" em conversas anteriores, apenas do texto final que produziu.

### Tipos de content guardados no DB

| O que é guardado | role | content |
|------------------|------|---------|
| Mensagem do utilizador | `user` | Texto plain |
| Ficheiro carregado | `user` | Texto formatado com dados do CSV |
| Resposta final do agente | `assistant` | Texto plain (concatenação de todos os text blocks) |

Os widgets (gráficos, tabelas, KPIs) e os dashboards **não são guardados** como mensagens — são renderizados no momento e apenas o dashboard tem persistência (via tabela `dashboards`).

---

## 8. Artifact Renderer — HTML/SVG inline

### O que são artifacts

Quando o Claude gera um bloco de código ` ```html ` ou ` ```svg ` na sua resposta de texto, o frontend converte-o automaticamente num iframe sandboxado renderizado inline.

### Como é detetado

Após o stream terminar (quando o `ReadableStream` fecha), a função `postProcessArtifacts` é chamada com o texto acumulado:

```javascript
// index.html
const ARTIFACT_RE = /```(html|svg|jsx)\n([\s\S]*?)```/g;
if (!ARTIFACT_RE.test(text)) return; // sem artifacts — não modifica nada
```

Se encontrar blocos, reconstrói o elemento de mensagem:
- **Texto antes/depois** do bloco → `<div style="white-space:pre-wrap">`
- **Bloco html/svg** → widget artifact com iframe

### Como o iframe é criado

Para `html`:
```javascript
// Se o código começa com <!DOCTYPE, usa tal qual
// Se não, injeta wrapper com Chart.js CDN:
srcdoc = `<!DOCTYPE html><html>
  <head><script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/..."></script></head>
  <body>${code}</body>
</html>`;
```

Para `svg`:
```javascript
srcdoc = `<!DOCTYPE html><html><body style="margin:0">${code}</body></html>`;
```

O `srcdoc` é atribuído via `requestAnimationFrame` após o elemento estar no DOM (evita race conditions).

O iframe usa `sandbox="allow-scripts"` — scripts podem correr, mas não têm acesso ao DOM pai, cookies, ou rede.

### Como instruir o Claude a gerar artifacts

O `artifact_hint` injetado no system prompt instrui o Claude:

```
ARTIFACTS INLINE: Quando precisares de mostrar uma visualização ou código HTML/SVG
diretamente no chat (não como dashboard persistente), produz um bloco de código
markdown com a linguagem 'html' ou 'svg'.
```

Exemplos de prompts que ativam artifacts:
- *"Gera um gráfico de barras HTML com Chart.js"*
- *"Mostra um SVG com um diagrama de fluxo"*
- *"Cria uma visualização inline"*

---

## 9. Dashboards persistentes

### Diferença entre artifact e dashboard

| | Artifact | Dashboard |
|---|---------|-----------|
| Trigger | Bloco ```html no texto | Tool `gerar_dashboard` chamada explicitamente |
| Persistência | Não — só existe enquanto a página está aberta | Sim — guardado no SQLite |
| URL partilhável | Não | Sim (`/dashboards/{id}`) |
| Auth necessária | N/A | Não — URL é pública (por design do PoC) |
| Quando usar | Visualizações rápidas inline | Relatórios para guardar e partilhar |

### Fluxo de criação de dashboard

```
1. Claude chama gerar_dashboard(titulo="...", html="<div>...")
2. tools.py devolve: {"widget": "dashboard", "titulo": "...", "html": "..."}
3. agent_engine.py:
   - Gera ID único: uuid4().hex[:12]  (ex: "a3f2c8e1b047")
   - Insere na tabela dashboards: (id, user_id, titulo, html, created_at)
   - Emite SSE: {"type": "dashboard", "url": "/dashboards/a3f2c8e1b047", "titulo": "..."}
   - Devolve ao Claude: {"status": "ok", "url": "/dashboards/a3f2c8e1b047"}
4. Browser recebe SSE → renderiza iframe apontando para /dashboards/a3f2c8e1b047
5. GET /dashboards/a3f2c8e1b047 → server.py injeta o HTML no DASHBOARD_TEMPLATE
   (template inclui Chart.js CDN + estilos base + auto-resize via postMessage)
```

### O HTML que o Claude gera para um dashboard

O Claude escreve apenas o **conteúdo do body** — não o HTML completo. O servidor envolve-o no template. As classes CSS que pode usar:

```
.kpi-card          → card de métrica com gradiente escuro
.chart-container   → container de gráfico com fundo branco e borda
.data-table        → tabela de dados estilizada
.dashboard-grid    → grid responsivo auto-fit min 300px
.dashboard-row     → linha flex para alinhar elementos
.section-title     → título de secção
```

Exemplo do que o Claude gera para `html` de um dashboard:
```html
<div class="dashboard-row">
    <div class="kpi-card">
        <h3>Total Defeitos</h3>
        <div class="value">200<span class="unit">defeitos</span></div>
    </div>
</div>
<div class="chart-container">
    <h3>Distribuição por Tipo</h3>
    <canvas id="chart1"></canvas>
    <script>
        new Chart(document.getElementById('chart1'), {
            type: 'pie',
            data: { labels: ['lixo', 'falta_tinta'], datasets: [{ data: [62, 31] }] }
        });
    </script>
</div>
```

---

## 10. Execução de código Python

### Como funciona

A tool `executar_python` permite ao Claude escrever e executar código Python arbitrário num subprocess isolado.

**Fluxo:**
```
1. Claude chama: executar_python(codigo="import math\nprint(math.sqrt(144))", descricao="Raiz quadrada de 144")
2. tools.py:
   a. Verifica se o código contém strings bloqueadas:
      ["import os", "import sys", "import subprocess", "import socket",
       "open(", "__import__", "exec(", "eval(", "compile("]
   b. Se bloqueado → devolve erro imediatamente (sem execução)
   c. Escreve código num ficheiro temporário (.py)
   d. subprocess.run([sys.executable, tmp_path], timeout=30, capture_output=True)
   e. Remove o ficheiro temporário (try/finally)
3. Retorna: {"output": "12.0\n", "sucesso": True}
4. agent_engine.py emite SSE: {"type": "tool_use", "name": "executar_python", "result": {...}}
5. Claude recebe o output e integra-o na sua resposta
```

### O que o Claude pode fazer com executar_python

```python
# Cálculos matemáticos
import math
print(math.factorial(10))

# Estatísticas
import statistics
dados = [10, 25, 33, 18, 42]
print(f"Média: {statistics.mean(dados):.2f}")
print(f"Mediana: {statistics.median(dados)}")

# Análise de dados com pandas (se instalado no ambiente)
import pandas as pd
df = pd.DataFrame({'a': [1,2,3], 'b': [4,5,6]})
print(df.describe())

# JSON
import json
data = {"chave": "valor"}
print(json.dumps(data, indent=2))

# Datetime
from datetime import datetime, timedelta
amanha = datetime.now() + timedelta(days=1)
print(amanha.strftime("%Y-%m-%d"))
```

### O que está bloqueado

```python
import os          # → "Operação não permitida: 'import os' está bloqueado"
import sys         # → bloqueado
import subprocess  # → bloqueado
import socket      # → bloqueado
open(              # → bloqueado (sem acesso ao filesystem)
__import__         # → bloqueado (bypass de imports)
exec(              # → bloqueado
eval(              # → bloqueado
compile(           # → bloqueado
```

**Nota:** Estas verificações são por correspondência de string. São suficientes para um PoC interno. Um utilizador determinado poderia contorná-las com técnicas avançadas — não usar em contextos públicos sem sandbox mais robusto.

---

## 11. Autenticação e sessões

### Login

```
POST /auth/login
Body: {"email": "rui@demo.com", "password": "rui123"}

→ {
    "token": "eyJhbGciOiJIUzI1NiJ9...",
    "nome": "Rui",
    "role": "responsavel"
  }
```

O token JWT contém:
```json
{
  "user_id": 2,
  "nome": "Rui",
  "role": "responsavel",
  "exp": 1740600000
}
```

O token é assinado com `JWT_SECRET` (configurável via `.env`). Expira ao fim de `JWT_EXPIRY_HOURS` horas (padrão: 8).

### Autorização

Todos os endpoints protegidos verificam o header:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9...
```

O endpoint `/dashboards/{id}` é público (sem auth) por design — os IDs são UUIDs hexadecimais de 12 caracteres, suficientemente difíceis de adivinhar para um PoC.

### Verificação de acesso aos agentes

Quando o utilizador tenta criar uma conversa com um agente, o servidor verifica a tabela `user_agentes`:

```sql
SELECT 1 FROM user_agentes WHERE user_id = ? AND agente_id = ?
```

Se não existir entrada, devolve `403 Forbidden`.

---

## 12. Limites e comportamentos de fronteira

| Limite | Valor | Onde está definido |
|--------|-------|-------------------|
| Histórico máximo enviado ao Claude | 20 mensagens | `MAX_HISTORY = 20` em `agent_engine.py` |
| Iterações máximas do loop de tool use | 8 | `max_iterations = 8` em `agent_engine.py` |
| Max tokens na resposta do Claude | 4096 | `max_tokens=4096` na chamada à API |
| Linhas de preview do ficheiro carregado | 10 | `df.head(10)` em `server.py` |
| Linhas de dados completos enviados ao Claude | 100 | `df.head(100)` em `server.py` |
| Output máximo de executar_python | 5000 chars | `result.stdout[:5000]` em `tools.py` |
| Stderr máximo em caso de erro Python | 2000 chars | `result.stderr[:2000]` em `tools.py` |
| Timeout de execução Python | 30 segundos | `timeout=30` em `tools.py` |
| Tipos de ficheiro aceites para upload | .csv, .xlsx | `server.py` |
| Colunas categóricas analisadas no upload | 5 primeiras | `df.select_dtypes(...)[:5]` em `server.py` |
| Top valores por coluna categórica | 5 | `.head(5)` em `server.py` |

### O que acontece quando os limites são atingidos

- **20 mensagens de histórico:** As mensagens mais antigas são simplesmente ignoradas. O Claude não tem contexto do que foi dito antes. Não há erro.
- **8 iterações de tool use:** O loop termina. A última resposta parcial é guardada no DB e o SSE `done` é emitido. O Claude pode não ter terminado a sua análise.
- **Ficheiro com >100 linhas:** Apenas as primeiras 100 são enviadas ao Claude. As estatísticas `describe()` e as distribuições são calculadas sobre o ficheiro completo.
- **executar_python timeout:** Devolve `{"erro": "Timeout: a execução excedeu 30 segundos."}` ao Claude, que explica ao utilizador.
- **API key inválida:** Emite SSE `{"type": "error", "content": "API key inválida..."}` e termina o stream.

---

## 13. Custos de tokens — o que gasta o quê

Esta é uma das partes mais importantes para perceber antes de usar o sistema intensivamente.

### Princípio fundamental: o Claude não tem memória

**O Claude não guarda nada entre requests.** Não existe "sessão" no lado da Anthropic. Cada vez que envias uma mensagem, o servidor reconstrói toda a conversa do zero e envia-a completa à API. Isto significa:

> Cada pergunta que fazes = system prompt + histórico completo das últimas 20 mensagens + a tua pergunta nova — **tudo enviado de novo**.

Isto é como funciona qualquer sistema baseado em LLMs (incluindo o próprio Claude.ai). A diferença é que o QHub guarda o histórico em SQLite e reconstitui-o em cada pedido.

---

### Preciso de fazer upload do CSV de novo depois de fazer uma pergunta?

**Não.** O upload guarda o conteúdo do ficheiro como uma mensagem `role="user"` na tabela `mensagens` do SQLite. Essa mensagem fica lá indefinidamente enquanto a conversa existir.

O que acontece nas perguntas seguintes:

```
Upload CSV  →  mensagem "user" guardada no DB (uma vez só)
                        │
Pergunta 1  →  [system_prompt] + [msg_csv] + [pergunta_1]  →  Claude responde
Pergunta 2  →  [system_prompt] + [msg_csv] + [pergunta_1] + [resp_1] + [pergunta_2]  →  Claude responde
Pergunta 3  →  [system_prompt] + [msg_csv] + [pergunta_1] + [resp_1] + [pergunta_2] + [resp_2] + [pergunta_3]
...
```

O CSV viaja em **cada chamada** enquanto estiver dentro da janela de 20 mensagens. Não precisas de o carregar de novo — mas estás a pagar pelos seus tokens em cada pergunta.

### Quando é que o CSV "desaparece" do contexto?

Quando a conversa acumula mais de 20 mensagens, as mais antigas saem da janela. Como o upload é tipicamente a primeira mensagem, após **~10 trocas** (20 mensagens = 10 pares user/assistant) o CSV já não está no contexto enviado ao Claude.

A partir desse ponto, o Claude não "vê" mais os dados do ficheiro. Se continuares a perguntar sobre eles, o Claude vai responder com base no que ainda está no histórico (as últimas 20 msgs) — que poderá não incluir o CSV.

**Solução:** Para análises longas de ficheiros externos, abre uma nova conversa e faz upload de novo.

---

### Estimativa de tokens por operação

Os preços Anthropic para `claude-sonnet-4` (valores indicativos, verificar em anthropic.com):
- Input: ~$3 / 1M tokens
- Output: ~$15 / 1M tokens

| Operação | Input tokens (estimativa) | Output tokens (estimativa) | Custo aproximado |
|----------|--------------------------|---------------------------|-----------------|
| Pergunta simples (1ª msg, sem histórico) | ~600 (system) + ~20 (pergunta) = **~620** | ~150 | ~$0.004 |
| Pergunta com tools (ex: top_defeitos + gráfico) | ~620 + ~200 (def. tools) = **~820** por iteração × 2-3 iterações | ~100 por iter. | ~$0.007–0.010 |
| Pergunta com CSV carregado (defeitos.csv 100 linhas) | ~620 + **~3.000 (CSV)** = ~3.620 | ~200 | ~$0.014 |
| Pergunta 5 numa conversa com CSV | ~620 + ~3.000 (CSV) + ~800 (4 trocas) = **~4.420** | ~200 | ~$0.016 |
| Gerar dashboard complexo | ~820 × 4 iterações = **~3.280** | ~600 (HTML longo) × 4 = ~2.400 | ~$0.046 |
| executar_python simples | ~820 + ~50 (código) = **~870** por iter. × 2 | ~50 | ~$0.006 |

> **Nota:** 1 token ≈ 4 caracteres em inglês / ~3 caracteres em português. O system prompt do QHub tem ~600 tokens, o `defeitos.csv` formatado tem ~3.000 tokens.

---

### Comparação: usar tools vs. fazer upload do CSV

O QHub tem duas formas de o Claude aceder a dados:

| | Tools (contar_defeitos, top_defeitos, etc.) | Upload do CSV |
|---|---|---|
| O que é enviado ao Claude | Apenas o **resultado** da query (ex: `{"total": 200, "por_tipo": {...}}`) | O **conteúdo completo** (até 100 linhas + stats) |
| Tokens de input por mensagem | ~200–500 tokens (resultado pequeno) | ~3.000 tokens (CSV completo) |
| Flexibilidade | Limitado às queries pré-definidas | Claude pode analisar qualquer padrão |
| Custo por pergunta | Baixo | Alto (paga o CSV em cada pergunta) |
| Melhor para | Queries repetidas sobre defeitos.csv | Análise de ficheiros externos novos |

**Regra prática:**
- Para analisar os **dados de defeitos** do sistema → usa as **tools** (muito mais barato)
- Para analisar um **ficheiro externo** que trazes → usa o **upload**

---

### Quanto gasta uma sessão típica?

**Sessão típica com tools (sem upload):**
```
5 perguntas, cada com 2 iterações de tool use
Input:  5 × (620 + 200 tools + 400 histórico crescente) × 2 iter. = ~12.200 tokens
Output: 5 × 200 tokens = ~1.000 tokens
Custo:  (12.200 × $3 + 1.000 × $15) / 1.000.000 ≈ $0.05
```

**Sessão com upload de CSV (defeitos.csv, 10 perguntas):**
```
1 upload + 10 perguntas
Input:  10 × (620 + 3.000 CSV + histórico crescente) ≈ 40.000 tokens
Output: 10 × 250 = 2.500 tokens
Custo:  (40.000 × $3 + 2.500 × $15) / 1.000.000 ≈ $0.16
```

**Gerar um dashboard completo (pedido único):**
```
3–4 iterações (queries + rendering)
Input:  4 × 1.200 = ~4.800 tokens
Output: 4 × 800 = ~3.200 tokens (HTML pode ser longo)
Custo:  (4.800 × $3 + 3.200 × $15) / 1.000.000 ≈ $0.06
```

---

### Dicas para reduzir custos

1. **Usa as tools em vez de upload** sempre que os dados já estejam no `defeitos.csv`
2. **Mantém conversas curtas e focadas** — o histórico cresce e cada pergunta fica mais cara
3. **Para análises longas de ficheiros externos**, faz o upload, faz todas as perguntas que precisas na mesma sessão, e fecha
4. **Evita pedir dashboards desnecessariamente** — são as operações mais caras (HTML longo no output)
5. **Abre nova conversa** para um novo tema em vez de continuar a mesma — histórico limpo = input menor
6. **O upload do CSV conta como ~3.000 tokens de input em CADA pergunta** subsequente — não é de graça manter o ficheiro "disponível"
