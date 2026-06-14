# Projeto: AI Agent API

> Agente de IA com FastAPI + Supabase. Leia este arquivo inteiro antes de qualquer tarefa.

---

## Stack

- **Runtime**: Python 3.12
- **API**: FastAPI 0.115+
- **Banco de dados**: Supabase (Postgres 15) via `supabase-py`
- **ORM/Queries**: Raw SQL com `supabase-py` client — sem ORM
- **Autenticação**: Supabase Auth (JWT)
- **Agente/LLM**: Anthropic SDK (`anthropic` Python) — modelo padrão `claude-sonnet-4-6`
- **Validação**: Pydantic v2
- **Testes**: pytest + pytest-asyncio
- **Linter/Formatter**: ruff + black
- **Gerenciador de deps**: uv (não pip direto)

---

## Estrutura do projeto

```
project/
├── app/
│   ├── main.py            # Entrypoint FastAPI, lifespan, routers
│   ├── config.py          # Settings via pydantic-settings
│   ├── dependencies.py    # FastAPI Depends: auth, supabase client
│   ├── agents/
│   │   ├── base.py        # Classe base do agente
│   │   └── [nome].py      # Agentes específicos
│   ├── routers/
│   │   └── [recurso].py   # Um arquivo por domínio
│   ├── schemas/
│   │   └── [recurso].py   # Pydantic models (request/response)
│   ├── services/
│   │   └── [recurso].py   # Lógica de negócio, sem HTTP
│   └── utils/
│       └── supabase.py    # Helper do cliente Supabase
├── tests/
│   ├── conftest.py
│   └── test_[recurso].py
├── .env                   # NUNCA commitar
├── .env.example           # Commitar — sem valores reais
├── CLAUDE.md              # Este arquivo
└── pyproject.toml
```

---

## Variáveis de ambiente obrigatórias

```env
# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...   # Apenas backend, nunca expor

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# App
APP_ENV=development                 # development | staging | production
SECRET_KEY=...                      # Para JWT local se necessário
```

**Regra crítica**: NUNCA hardcode de chaves no código. Use sempre `settings.NOME_DA_VAR`.

---

## Convenções de código

### Python geral
- Type hints obrigatórios em todas as funções e métodos
- Docstrings em funções públicas (formato Google Style)
- Máximo 100 caracteres por linha
- Imports ordenados: stdlib → third-party → local (ruff cuida disso)

### FastAPI
- Cada domínio tem seu próprio router em `app/routers/`
- Nunca lógica de negócio dentro do router — delegar para `services/`
- Sempre usar `Depends()` para injeção de dependências (auth, db client)
- Responses sempre tipadas com schema Pydantic
- Status codes explícitos em cada endpoint

```python
# BOM
@router.post("/mensagens", response_model=MensagemResponse, status_code=201)
async def criar_mensagem(
    payload: MensagemCreate,
    user: User = Depends(get_current_user),
    svc: MensagemService = Depends(get_mensagem_service),
) -> MensagemResponse:
    return await svc.criar(payload, user.id)

# RUIM — lógica no router, sem tipagem
@router.post("/mensagens")
async def criar_mensagem(payload: dict):
    result = supabase.table("mensagens").insert(payload).execute()
    return result
```

### Supabase / banco
- Usar `supabase-py` client, nunca psycopg2 diretamente
- Queries em `services/`, nunca em `routers/`
- Tratamento explícito de erros do Supabase (`.data`, `.error`)
- Sem ORM — queries diretas via client ou RPC para operações complexas
- Migrations gerenciadas pelo Supabase Dashboard ou CLI

### Agentes / LLM
- Todo agente herda de `BaseAgent` em `app/agents/base.py`
- Prompts de sistema em constantes no topo do arquivo, nunca inline
- Histórico de conversa sempre como lista de `MessageParam`
- Streaming via `client.messages.stream()` quando a resposta for longa
- Sempre definir `max_tokens` explicitamente — nunca omitir

```python
# BOM
SYSTEM_PROMPT = """Você é um assistente jurídico especializado em..."""

class MeuAgente(BaseAgent):
    async def processar(self, mensagem: str, historico: list) -> str:
        response = await self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=historico + [{"role": "user", "content": mensagem}],
        )
        return response.content[0].text
```

### Pydantic v2
- Usar `model_config = ConfigDict(...)` — não `class Config`
- Sempre separar schema de criação, atualização e resposta
- Nunca expor campos internos (ex: `service_role_key`, `password_hash`) nos schemas de response

---

## Testes

```bash
# Rodar todos os testes
pytest

# Com cobertura
pytest --cov=app --cov-report=term-missing

# Apenas um módulo
pytest tests/test_agente.py -v
```

- **Regra**: nenhum PR sem testes para o código novo
- Usar `pytest-asyncio` para funções `async`
- Mocks do Supabase client com `unittest.mock.AsyncMock`
- Fixtures de autenticação em `conftest.py` — não repetir em cada teste

---

## Linting e formatação

```bash
# Formatar
black app/ tests/

# Lint
ruff check app/ tests/

# Ambos juntos (usar antes de qualquer commit)
ruff check --fix app/ tests/ && black app/ tests/
```

**Regra**: rodar lint antes de sugerir qualquer PR como pronto.

---

## Comandos essenciais

```bash
# Instalar dependências
uv sync

# Rodar servidor de desenvolvimento
uvicorn app.main:app --reload --port 8000

# Rodar testes
pytest

# Verificar tipos
pyright app/

# Gerar migration (Supabase CLI)
supabase db diff --schema public -f nome_da_migration

# Aplicar migrations
supabase db push
```

---

## Regras críticas — nunca violar

1. **NUNCA commitar `.env`** — está no `.gitignore`. Usar `.env.example` com placeholders
2. **NUNCA expor `SUPABASE_SERVICE_ROLE_KEY`** em logs, responses ou frontend
3. **NUNCA usar `*` em imports** — sempre imports explícitos
4. **NUNCA deletar a pasta `/tests`** sem confirmação explícita
5. **NUNCA fazer queries SQL raw com f-string** — usar parâmetros do client Supabase (previne SQL injection)
6. **NUNCA alterar tabelas do Supabase diretamente** — sempre via migration versionada

---

## Fluxo de trabalho esperado

1. Entender o requisito → perguntar se ambíguo
2. Escrever/atualizar schema Pydantic
3. Implementar service
4. Implementar router
5. Escrever testes
6. Rodar `pytest` — corrigir falhas antes de reportar como pronto
7. Rodar lint (`ruff` + `black`)
8. Sugerir mensagem de commit em Conventional Commits

---

## Gotchas conhecidos do projeto

- O client Supabase é assíncrono — usar `await` em todas as queries
- `supabase-py` v2 retorna `.data` como lista mesmo para `.single()` — verificar antes de acessar `[0]`
- FastAPI com `lifespan` para inicializar/fechar o client Supabase — não usar `@app.on_event` (deprecated)
- Pydantic v2 não aceita `orm_mode = True` — usar `model_config = ConfigDict(from_attributes=True)`
- Ao usar streaming do Anthropic, o response type muda — tratar `with client.messages.stream(...) as s`
