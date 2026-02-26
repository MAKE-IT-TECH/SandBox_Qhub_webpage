# QHub — Base de Dados Remota com Atualização Automática
### Documento de Arquitetura e Plano de Implementação
*Fevereiro 2026*

---

## 1. O Problema Atual

O QHub PoC funciona com um ficheiro CSV estático (defeitos.csv) com 200 registos fixos. Esta abordagem é suficiente para uma prova de conceito, mas tem três limitações fundamentais:

- Os dados nunca mudam — o agente responde sempre com base nos mesmos 200 defeitos de fevereiro de 2026
- Não há inserção de dados reais — os operadores da fábrica não têm como registar defeitos novos
- Não há histórico acumulado — é impossível fazer análises de tendência, sazonalidade ou comparação entre períodos

---

## 2. A Questão Central: De Onde Vêm os Dados?

Antes de definir a arquitetura técnica, é necessário responder a uma pergunta de negócio: como é que os defeitos são registados atualmente na fábrica? Há quatro cenários possíveis:

| Cenário | Situação | O que é preciso construir |
|---|---|---|
| A | A fábrica tem MES/ERP | Conector que lê o sistema existente e sincroniza com QHub DB |
| B | Operadores registam em papel/Excel | Formulário digital na webapp QHub para substituir o papel |
| C | Export manual periódico | Upload de CSV/Excel pelo responsável — já implementado no upgrade |
| D | Sensores/máquinas IoT | Pipeline de ingestão de dados em tempo real (mais complexo) |

> ⚠ **Nota:** Este documento cobre o Cenário B (o mais comum em PMEs industriais) como caso principal, com referências aos outros cenários onde relevante.

---

## 3. Arquitetura Proposta

A solução divide-se em três camadas independentes que podem ser implementadas gradualmente:

### 3.1 Camada de Ingestão — Onde os Dados Entram

Esta camada substitui o CSV estático por uma fonte de dados dinâmica. Dependendo do cenário da fábrica:

- **Cenário B:** formulário de registo de defeitos na webapp (operadores inserem diretamente)
- **Cenário C:** endpoint de upload já implementado no upgrade anterior
- **Cenário A:** script de sincronização com o ERP/MES existente

### 3.2 Camada de Armazenamento — A Base de Dados Remota

A DB SQLite local é substituída por PostgreSQL num servidor remoto. PostgreSQL é escolhido porque:

- Suporta múltiplas conexões simultâneas (SQLite não escala com vários utilizadores)
- Tem tipos de dados avançados para timestamps e dados industriais
- É gratuito, maduro e tem excelente suporte em Python
- Serviços cloud como Supabase ou Railway oferecem PostgreSQL gratuito para PoC

### 3.3 Camada de Acesso — As Tools do Agente

As tools em `tools.py` são reescritas para fazer queries SQL dinâmicas à DB remota em vez de ler o CSV. Isto permite ao agente responder a perguntas como *"quantos defeitos no último mês?"* ou *"qual o turno com mais defeitos esta semana?"*

---

## 4. Esquema da Base de Dados de Defeitos

A tabela principal de defeitos replica a estrutura do CSV atual mas adiciona campos para suportar dados reais:

```sql
CREATE TABLE defeitos (
  id           SERIAL PRIMARY KEY,
  data         DATE NOT NULL,
  turno        VARCHAR(10) NOT NULL,  -- manha/tarde/noite
  operador     VARCHAR(100) NOT NULL,
  tipo_defeito VARCHAR(50) NOT NULL,
  material     VARCHAR(50) NOT NULL,
  rack         VARCHAR(10),
  posicao      INTEGER,
  created_at   TIMESTAMP DEFAULT NOW(),
  created_by   INTEGER REFERENCES users(id)  -- quem registou
);
```

Tabela auxiliar para configuração dinâmica (permite adicionar novos tipos de defeito ou materiais sem alterar código):

```sql
CREATE TABLE lookup_valores (
  categoria  VARCHAR(50),  -- 'tipo_defeito', 'material', 'turno'
  valor      VARCHAR(100),
  ativo      BOOLEAN DEFAULT TRUE
);
```

---

## 5. Feature: Formulário de Registo de Defeitos

Esta é a feature mais importante para o Cenário B. Os operadores precisam de uma forma rápida e simples de registar defeitos diretamente na webapp, substituindo o papel ou Excel.

### 5.1 Interface — O que o Operador Vê

Um novo botão **"Registar Defeito"** aparece na sidebar para utilizadores com role `operadora` ou `responsavel`. Ao clicar, abre um modal com:

- Data e hora (preenchidos automaticamente, editáveis)
- Turno (dropdown: Manhã / Tarde / Noite — pré-selecionado com base na hora atual)
- Operador (preenchido automaticamente com o utilizador logado)
- Tipo de defeito (dropdown com os tipos conhecidos)
- Material (dropdown: ABS_Cinza, PP_Negro, etc.)
- Rack e Posição (campos opcionais)
- Botão **Guardar** — submete e fecha o modal

### 5.2 Backend — Endpoint de Inserção

```
POST /defeitos
Authorization: Bearer {token}
Body: {
  data, turno, operador, tipo_defeito, material, rack?, posicao?
}

Retorna: { id: 42, mensagem: "Defeito registado com sucesso" }
```

> ⚠ **Nota:** O campo `operador` é preenchido automaticamente a partir do JWT (`user_id`) — o operador não pode registar defeitos em nome de outro utilizador.

### 5.3 Validações

- `turno` deve ser um de: `manha`, `tarde`, `noite`
- `tipo_defeito` deve existir na tabela `lookup_valores`
- `data` não pode ser mais de 7 dias no passado (evita erros de digitação)
- Todos os campos obrigatórios validados com HTTP 422 se em falta

---

## 6. Atualização Automática Diária

Para o Cenário C (export manual) ou para sincronização com sistemas externos, é possível criar um processo automático que corre todos os dias a uma hora definida.

### 6.1 Script de Sincronização

```python
# sync_defeitos.py — corre todos os dias às 06:00
import pandas as pd
import psycopg2

def sync_csv_para_db(csv_path, conn_string):
    df = pd.read_csv(csv_path)
    conn = psycopg2.connect(conn_string)
    cursor = conn.cursor()
    for _, row in df.iterrows():
        cursor.execute(
            "INSERT INTO defeitos (data, turno, operador, tipo_defeito, material, rack, posicao)"
            "VALUES (%s, %s, %s, %s, %s, %s, %s)"
            "ON CONFLICT (id) DO NOTHING",  -- evita duplicados
            (row.data, row.turno, row.operador, row.tipo_defeito, row.material, row.rack, row.posicao)
        )
    conn.commit()
    conn.close()
```

### 6.2 Configuração do Cron Job (Linux)

```bash
# Editar crontab:
crontab -e

# Linha a adicionar — corre às 06:00 todos os dias:
0 6 * * * /path/to/venv/bin/python /path/to/sync_defeitos.py >> /var/log/qhub_sync.log 2>&1
```

### 6.3 Alternativa — Supabase com Scheduled Functions

Se usar Supabase como base de dados remota (opção recomendada para simplicidade), é possível configurar uma Edge Function que é invocada automaticamente via scheduled trigger, sem necessidade de servidor dedicado.

---

## 7. Reescrita das Tools para DB Remota

As tools em `tools.py` passam a fazer queries SQL dinâmicas em vez de ler o CSV. Isto torna as análises muito mais poderosas:

### 7.1 Exemplo: contar_defeitos com filtros temporais

```python
def contar_defeitos(tipo_defeito=None, periodo='total', data_inicio=None, data_fim=None):
    query = "SELECT COUNT(*) FROM defeitos WHERE 1=1"
    params = []
    if tipo_defeito:
        query += " AND tipo_defeito = %s"
        params.append(tipo_defeito)
    if periodo == 'hoje':
        query += " AND data = CURRENT_DATE"
    elif periodo == 'semana':
        query += " AND data >= CURRENT_DATE - INTERVAL '7 days'"
    elif periodo == 'mes':
        query += " AND data >= DATE_TRUNC('month', CURRENT_DATE)"
    if data_inicio:
        query += " AND data >= %s"
        params.append(data_inicio)
    # ... executar query e retornar resultado
```

### 7.2 Novas Tools possíveis com DB

| Tool | O que faz | Parâmetros |
|---|---|---|
| `tendencia_defeitos` | Evolução ao longo do tempo (diária/semanal/mensal) | `periodo`, `tipo_defeito?` |
| `comparar_turnos` | Comparação de turnos num período | `data_inicio`, `data_fim` |
| `comparar_operadores` | Performance por operador | `turno?`, `periodo?` |
| `alertas_defeitos` | Identificar picos anómalos | `threshold`, `periodo` |
| `ultimos_registos` | Últimos N defeitos inseridos | `n=10` |

---

## 8. Opções de Hosting da Base de Dados

Para uma PoC ou piloto, há várias opções gratuitas ou de baixo custo:

| Opção | Tipo | Custo | Vantagens | Limitações |
|---|---|---|---|---|
| **Supabase** | PostgreSQL cloud | Grátis (500MB) | Dashboard web, API REST automática, auth integrada | 500MB no plano grátis |
| **Railway** | PostgreSQL cloud | Grátis (1GB) | Deploy fácil, sem configuração | Sleep após inatividade |
| **Neon** | PostgreSQL serverless | Grátis | Serverless, scale-to-zero | Cold start lento |
| **VPS próprio** | Self-hosted | ~5€/mês | Controlo total, sem limites | Requer manutenção |
| **Turso** | SQLite cloud | Grátis | Zero migração do código atual | Menos features que PostgreSQL |

**Recomendação para começar: Supabase.** Tem dashboard web para visualizar os dados diretamente, API REST automática que pode ser usada por outros sistemas da fábrica, e a migração do código é simples — apenas mudar a connection string.

---

## 9. Plano de Implementação

### Fase 1 — Base de Dados Remota (1-2 dias)
1. Criar conta no Supabase e criar a tabela `defeitos` com o esquema definido
2. Migrar os 200 registos do CSV atual para a DB (script de migração one-shot)
3. Atualizar `tools.py` para usar `psycopg2` ou `supabase-py` em vez de `csv.reader`
4. Testar: o agente deve responder com os mesmos resultados de antes

### Fase 2 — Formulário de Registo (2-3 dias)
1. Criar endpoint `POST /defeitos` no `server.py`
2. Criar modal de registo no frontend (`static/index.html`)
3. Testar registo de defeitos por parte de um operador
4. Verificar que o agente "vê" imediatamente os novos registos

### Fase 3 — Atualização Automática (1 dia)
1. Se Cenário C: o endpoint de upload já funciona — ligar ao script de inserção na DB
2. Se Cenário A: desenvolver conector com o ERP/MES específico
3. Configurar cron job ou Supabase scheduled function

### Fase 4 — Tools Enriquecidas (2-3 dias)
1. Adicionar parâmetros de período às tools existentes (`hoje`/`semana`/`mês`)
2. Implementar tool `tendencia_defeitos` para análises históricas
3. Atualizar `TOOL_DEFINITIONS` no `agent_engine.py`

---

## 10. Dependências Python a Adicionar

```
# requirements.txt — adicionar ao existente:
psycopg2-binary   # driver PostgreSQL
supabase          # cliente Supabase (opcional — só se usar Supabase)
python-dotenv     # já deve existir para o .env
```

---

## 11. Sumário

O salto do CSV estático para uma DB remota com atualização automática transforma o QHub de uma demo para um sistema utilizável em produção. Os pontos-chave são:

- A arquitetura mantém-se simples — FastAPI + PostgreSQL remoto, sem infraestrutura nova
- As tools do agente ficam muito mais poderosas com queries SQL dinâmicas e filtros temporais
- O formulário de registo é o coração do sistema — é o que alimenta a DB com dados reais
- Supabase é a opção recomendada para começar — grátis, sem servidor para gerir, dashboard incluído
- A implementação pode ser faseada — Fase 1 sozinha já resolve o problema principal

> ⚠ **Nota:** Este documento assume que os dados de defeitos são inseridos manualmente por operadores (Cenário B). Se a fábrica já tiver um sistema de registo digital, o Cenário A (conector ERP) é mais adequado e requer uma análise separada do sistema existente.