# Hub de I.A Jurídico Condominial — Design / Especificação

> Data: 2026-07-12 · Status: **Aprovado** (arquitetura) · Prazo-alvo do MVP rodando: **sexta 17/07/2026**

---

## 1. Visão

Plataforma de I.A jurídica **especializada em Direito Condominial**, para uso de um
escritório de advocacia condominialista. O coração é um **Agente Supervisor** que faz o
primeiro contato, conduz o onboarding do escritório e comanda uma **equipe de agentes
especialistas**. O diferencial competitivo é a **memória do cliente**: o acervo de cada
condomínio vive no Google Drive do escritório e alimenta um índice que todos os agentes
consultam, de modo que cada tarefa **segue o padrão já estabelecido** para aquele cliente.

**Público híbrido:** advogados condominialistas (linguagem técnica) e síndicos/administradoras
(linguagem acessível). Os agentes adaptam o registro conforme a pergunta.

---

## 2. Decisões tomadas (travadas)

| Tema | Decisão |
|---|---|
| Público | Híbrido: técnico + acessível, o agente adapta o tom |
| Especialistas | 4: Consultor Condominial, Inadimplência & Cobrança, Assembleias & Atas, Convenção/Regimento/Infrações |
| Supervisor | Orquestrador: primeiro contato + onboarding + roteamento |
| Orquestração | **Híbrido** — Supervisor roteia via *tool use*; usuário técnico pode escolher especialista direto |
| Google | **Single-tenant agora, arquitetado para SaaS depois**. OAuth em modo teste (conta do próprio escritório) — funciona sem espera de verificação do Google |
| Memória | **Índice estruturado + leitura sob demanda** (Supabase espelha estrutura de pastas + metadados; agente lê arquivos relevantes na hora). Evolui para RAG com embeddings depois, sem retrabalho |

---

## 3. Arquitetura geral (fases)

Construída em 4 marcos back-to-back, cada um entregando algo utilizável:

- **M1 🧠 Cérebro** — Supervisor + onboarding + 4 especialistas condominiais. Sem dependência
  externa além da chave Anthropic. **É o primeiro build.**
- **M2 🦴 Espinha** — Modelo de dados no Supabase: escritório → condomínios → blocos →
  unidades + índice do acervo + histórico de interações.
- **M3 ✋ Mãos** — Integração Google Drive/Workspace (OAuth modo teste). Sincronizador varre o
  Drive, mapeia pasta→condomínio/bloco/unidade e grava no índice; Supervisor mostra o que
  identificou para confirmação.
- **M4 🧬 Memória** — Cada especialista consulta o índice + histórico do cliente antes de agir
  e segue o padrão anterior.

Dependências: M1 → (M2 → M3 → M4). M1 é independente e roda assim que houver chave Anthropic válida.

---

## 4. Modelo de dados (Espinha — M2)

Multi-tenant-ready desde o início: **toda** tabela de domínio carrega `escritorio_id`.

- `escritorios` — `id`, `nome`, `site`, `instagram`, `google_conectado`, `created_at`
  (hoje 1 linha; a coluna existe para virar SaaS sem migração dolorosa)
- `condominios` — `id`, `escritorio_id`, `nome`, `cnpj?`, `endereco?`, `drive_folder_id`, `status`
- `blocos` — `id`, `condominio_id`, `nome`, `drive_folder_id`
- `unidades` — `id`, `bloco_id`, `identificacao` (ex: "101"), `drive_folder_id`
- `drive_index` — `id`, `escritorio_id`, `drive_file_id`, `tipo`
  (`condominio|bloco|unidade|documento`), `condominio_id?`, `nome`, `caminho`, `mime`, `modified_at`, `synced_at`
- `interacoes` — `id`, `escritorio_id`, `condominio_id?`, `agente`, `pedido`, `resultado_resumo`,
  `documento_gerado?`, `created_at` → fonte do "seguir o padrão anterior"

Regras do projeto: queries via `supabase-py` em `services/`, nunca em routers; sem f-string em SQL;
migrations versionadas em `sql/`.

---

## 5. M1 — Cérebro (detalhado — primeiro build)

### 5.1 Agentes

Todos herdam de `BaseAgent` (`app/agents/base.py`, já existe, com streaming). Cada agente tem seu
`SYSTEM_PROMPT` como constante no topo do módulo.

| slug | nome | papel |
|---|---|---|
| `supervisor` | Supervisor | Primeiro contato; onboarding; roteia para especialistas via tool use; adapta o tom ao público |
| `consultor-condominial` | Consultor Condominial | Dúvidas gerais: Lei 4.591/64, arts. 1.331–1.358 do CC, convenção e regimento |
| `inadimplencia` | Inadimplência & Cobrança | Cobrança de cotas, notificação, ação de cobrança/execução, juros, multa, penhora |
| `assembleias` | Assembleias & Atas | Convocação, quórum, deliberações, impugnação, redação de atas |
| `convencao` | Convenção, Regimento & Infrações | Elaboração/revisão de convenção e regimento; multas, barulho, animais, áreas comuns |

Todos os prompts incluem as guardas do projeto: nunca inventar jurisprudência/artigo/súmula; sinalizar
quando algo precisa ser conferido; encerrar análises complexas lembrando que a resposta é apoio à
atuação profissional. Respostas sempre em pt-BR.

### 5.2 Orquestração híbrida

- **Roteamento (maestro):** o Supervisor recebe a mensagem e, via **tool use** da Anthropic, decide
  entre responder direto (onboarding/conversa) ou delegar a um especialista. Cada especialista é
  exposto como uma *tool* (`consultar_consultor`, `consultar_inadimplencia`, ...). A resposta do
  especialista volta ao usuário em streaming.
- **Atalho (advogado):** o front mantém os cards dos 4 especialistas; clicar num card conversa
  direto com ele, sem passar pelo Supervisor.
- No M1, os especialistas ainda **não** têm memória do cliente (isso é M4); respondem com seu
  conhecimento jurídico condominial. O gancho para a consulta ao Índice já fica previsto na interface
  do agente para não gerar retrabalho.

### 5.3 Registro e API

- `app/services/chat.py`: `_REGISTRO` passa a conter Supervisor + 4 especialistas condominiais
  (substituindo os agentes genéricos atuais). `listar_agentes()` alimenta os cards.
- Endpoints existentes reaproveitados: `GET /api/agentes`, `POST /api/chat` (streaming).
- Novo estado de onboarding é conduzido **pela conversa** com o Supervisor no M1 (persistência real
  na Espinha entra no M2); no M1 pode ser mantido em memória/sessão do front.

### 5.4 Frontend (M1)

Reaproveita `app/static/index.html` + `app.css`, re-tematizado para condominial:
- Tela inicial conduzida pelo **Supervisor** (primeiro contato/onboarding).
- Cards dos 4 especialistas (atalho direto).
- Seletor de modelo mantido (Sonnet/Haiku/Opus).
- Placeholder do seletor de **cliente (condomínio)** e do **status da conexão Google** — visíveis mas
  inertes no M1 (ativados em M2/M3).
- Identidade visual sóbria/jurídica, responsiva, tema claro/escuro.

### 5.5 Testes (M1)

- `tests/test_chat_condominial.py`: registro dos 5 agentes; `obter_agente` para slugs válidos/ inválidos;
  contrato do `/api/agentes`; roteamento do Supervisor (tool use mockado — sem chamar a API real).
- Mocks da Anthropic com `unittest.mock`. Manter suíte verde (`uv run pytest`) e lint (`ruff`, `black`).

---

## 6. M2 — Espinha (roadmap)

Criar as tabelas da seção 4 (migration em `sql/`), services de CRUD de condomínios/blocos/unidades,
e persistir o resultado do onboarding do Supervisor. Endpoints admin protegidos por `ADMIN_TOKEN`
(padrão já existente no projeto) até integrar Supabase Auth.

## 7. M3 — Mãos / Google Drive (roadmap)

- OAuth **modo teste** com a conta do escritório (escopo de leitura do Drive).
- **Convenção de pastas** no Drive: `Condomínio X / Bloco A / Unidade 101 / (documentos)`.
  Conteúdo pode estar desorganizado; o que importa é a hierarquia.
- Sincronizador varre o Drive, mapeia pasta→condomínio/bloco/unidade, grava em `drive_index`, e o
  Supervisor apresenta o resultado para confirmação humana.
- Passo-a-passo de configuração do Google Cloud será entregue ao usuário nesta fase.

## 8. M4 — Memória (roadmap)

Antes de agir, o especialista: (1) identifica o condomínio no Índice; (2) puxa `interacoes` anteriores
+ documentos relevantes via `drive_index`; (3) lê sob demanda os arquivos-modelo; (4) produz seguindo
o padrão. Cada tarefa concluída grava uma `interacao`. Evolução futura: embeddings/pgvector para busca
semântica no acervo.

---

## 9. Dependências externas (caminho crítico — responsabilidade do usuário)

1. 🔑 **ANTHROPIC_API_KEY** válida no `.env` (a atual retorna 401) — bloqueia qualquer resposta.
2. 🗄️ **Projeto Supabase** novo (URL + anon key + service role) — bloqueia M2+.
3. 🔐 **Projeto Google Cloud + OAuth** (tela de consentimento em modo teste) — bloqueia M3+.

## 10. Não-objetivos (YAGNI por enquanto)

- SaaS multi-escritório com onboarding self-service e verificação pública do app Google.
- RAG com embeddings (fica como evolução do M4).
- Pagamentos, billing, app mobile.
- O módulo de **Rifas** presente no repositório é **outro projeto**, sem relação com este hub.

## 11. Critérios de sucesso do MVP (sexta 17/07)

- Servidor sobe limpo; suíte de testes verde; lint limpo.
- Com chave Anthropic válida: Supervisor recebe o usuário, faz onboarding e **roteia** para os
  especialistas; cada especialista responde com conteúdo condominial correto e no tom adequado.
- Front condominial no ar com Supervisor + 4 cards, seletor de cliente e status Google (inertes até
  M2/M3).
- Espinha (M2) e conexão Google (M3) implementadas o quanto antes na sequência, single-tenant.
