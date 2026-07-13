# Hub de I.A Jurídico Condominial — Design / Especificação

> Data: 2026-07-12 · Rev. 3 · Status: **em revisão** · Prazo-alvo do MVP rodando: **sexta 17/07/2026**

---

## 1. Visão

**Ferramenta interna de um escritório de advocacia condominialista** (escritório do Dr. Wilker,
17+ anos na área). NÃO é um produto voltado ao condomínio/síndico — é o motor de trabalho do
escritório.

O núcleo **não é "um chat com I.A"** (um ChatGPT já faria isso). O núcleo é uma
**base de conhecimento por cliente**: cada demanda (notificação, petição, contrato, parecer)
é produzida **no padrão do próprio escritório**, lendo os documentos **daquele condomínio
específico** — convenção, regimento, atas, deliberações, contratos, petições e notificações
anteriores, pareceres, acordos e histórico de atendimento.

Critério de sucesso do projeto inteiro, nas palavras do Dr. Wilker:
> "o que precisamos aqui é **assertividade na leitura dos documentos do condomínio**."

Consequência de arquitetura: a integração com o **acervo (Google Drive / base de conhecimento)**
e a **memória do cliente** NÃO são "fase extra" — são **o produto**. O Supervisor que ingere os
documentos, identifica cliente por cliente e por data, organiza em pastas e vira a memória do
escritório é exatamente o fluxo validado com o Dr. Wilker.

**Diferencial (vs. ChatGPT / NotebookLM):** não é uma I.A genérica — são **agentes especialistas
prontos** + **memória/histórico** do acervo (notificações, atas, petições anteriores) que as
ferramentas genéricas não retêm. É um hub nichado para advogados condominialistas, com o conhecimento
jurídico do escritório embutido.

**Público primário:** advogados do escritório (registro técnico-jurídico).
**Evolução futura:** portal do síndico (o cliente abre demanda pelo portal → chega ao escritório
já classificada + rascunho da I.A). Fora do MVP.

---

## 2. Decisões tomadas (travadas)

| Tema | Decisão |
|---|---|
| Público primário | Escritório de advocacia condominialista (advogados); tom técnico-jurídico |
| Agentes especialistas | **Trabalho do escritório**: Notificações, Petições, Contratos, Pareceres, Consulta Histórica, Jurídico Geral (todos no domínio condominial) |
| Supervisor | Orquestrador: primeiro contato + onboarding + **ingestão/organização do acervo** + roteamento |
| Orquestração | Híbrido — Supervisor roteia via *tool use*; advogado pode escolher especialista direto |
| Google | Single-tenant agora (OAuth modo teste, conta do escritório), arquitetado para SaaS depois |
| Integração (Drive/Workspace) | Via **MCP** (Model Context Protocol): conector MCP lê os drives. A plataforma **também expõe endpoints MCP/API** para não ser fechada a outras ferramentas. Google primeiro; Microsoft/OneDrive depois |
| Dados & confidencialidade | Dados permanecem **na origem** (Drive do escritório) — indexamos metadados + texto extraído, **sem duplicar** o acervo. **Isolamento estrito** entre escritórios (tenants) e por condomínio: nada vaza entre clientes (requisito de 1ª classe, é dado jurídico) |
| Memória / acervo | **Núcleo do produto.** Índice estruturado + base documental por cliente no Supabase; leitura sob demanda. Evolui para RAG/embeddings depois |
| Fora do escopo | Agentes voltados ao condomínio/síndico (Inadimplência, Assembleias etc.); portal do síndico; API de processos/andamentos (custosa); Microsoft/OneDrive no MVP |

---

## 3. Arquitetura geral (fases)

- **M1 🧠 Cérebro** — Supervisor + onboarding + os 6 especialistas do escritório. Sem dependência
  externa além da chave Anthropic. Primeiro build.
- **M2 🦴 Espinha** — Supabase: escritório → condomínios → blocos → unidades + **base documental
  por cliente** + histórico de interações.
- **M3 ✋ Mãos** — Google Drive/Workspace via **conector MCP** (OAuth modo teste). Supervisor ingere o
  acervo, identifica cliente/data, mapeia e organiza, grava no índice + base documental. Plataforma
  também expõe endpoints MCP/API (sistema aberto).
- **M4 🧬 Memória** — Cada especialista consulta o acervo + histórico do cliente antes de agir e
  produz no padrão anterior. **É onde mora a "assertividade na leitura".**

Dependências: M1 → (M2 → M3 → M4). M3+M4 concentram o valor central; por isso entram o quanto antes
na sequência.

**Demo para o Dr. Wilker:** o que convence não são 6 agentes sem memória — é **uma fatia vertical**:
1 agente (ex.: Notificações) lendo os documentos reais de 1 condomínio e gerando o documento no
padrão do escritório. Priorizar essa fatia assim que M3 estiver de pé.

---

## 4. Modelo de dados (Espinha — M2)

Multi-tenant-ready: toda tabela de domínio carrega `escritorio_id`.

- `escritorios` — `id`, `nome`, `site`, `instagram`, `google_conectado`, `created_at`
- `condominios` — `id`, `escritorio_id`, `nome`, `cnpj?`, `endereco?`, `drive_folder_id`, `status`
- `blocos` — `id`, `condominio_id`, `nome`, `drive_folder_id`
- `unidades` — `id`, `bloco_id`, `identificacao` (ex: "101"), `drive_folder_id`
  (blocos/unidades são necessários para notificação a unidade específica)
- `drive_index` — espelho estrutural das pastas: `id`, `escritorio_id`, `drive_file_id`, `tipo`
  (`condominio|bloco|unidade|pasta`), `condominio_id?`, `nome`, `caminho`, `modified_at`, `synced_at`
- `documentos` — **base de conhecimento por cliente**: `id`, `escritorio_id`, `condominio_id`,
  `categoria` (`convencao|regimento|ata|deliberacao|contrato|peticao|notificacao|parecer|acordo|historico|outro`),
  `drive_file_id`, `nome`, `caminho`, `mime`, `modified_at`, `texto_extraido?` (preenchido no M4),
  `synced_at`
- `interacoes` — histórico do que cada agente fez: `id`, `escritorio_id`, `condominio_id?`, `agente`,
  `pedido`, `resultado_resumo`, `documento_gerado?`, `created_at` → parte do acervo ("histórico de
  atendimentos") e base do "seguir o padrão anterior"

Regras do projeto: queries via `supabase-py` em `services/`, nunca em routers; sem f-string em SQL;
migrations versionadas em `sql/`.

---

## 5. M1 — Cérebro (detalhado — primeiro build)

### 5.1 Agentes

Todos herdam de `BaseAgent` (`app/agents/base.py`, já existe, com streaming). Cada agente tem seu
`SYSTEM_PROMPT` como constante no topo do módulo.

| slug | nome | papel |
|---|---|---|
| `supervisor` | Supervisor / Agente Geral | Primeiro contato; onboarding do escritório (nome, site, Instagram); **ingestão automática** do acervo (aprende e monta a base ao mesmo tempo, sem processo manual — pede acesso ao Drive e organiza por condomínio/unidade/data); roteia para especialistas via tool use |
| `notificacoes` | Notificações | Redige notificações a partir de **comando simples em linguagem natural** (ex.: "cão fez sujeira no elevador") + normas internas do condomínio (convenção, regimento, atas, deliberações) + legislação, para a unidade/ocorrência informadas |
| `peticoes` | Petições | Redige peças processuais condominiais (inclui cobrança) no padrão do escritório |
| `contratos` | Contratos | Análise de risco, cláusulas, garantias, responsabilidades, adequação ao caso concreto; **alertas de vencimento** e **minutas de rescisão personalizadas** |
| `pareceres` | Pareceres | Pareceres jurídicos fundamentados nas normas internas + legislação |
| `consulta-historica` | Consulta Histórica | Responde fatos do acervo: síndico atual, último reajuste da taxa, deliberação sobre X — pesquisando atas/documentos |
| `juridico-geral` | Jurídico Geral | Dúvidas amplas de direito condominial com fundamentação, para o que não cai nos especialistas |

Guardas do projeto em todos os prompts: nunca inventar jurisprudência/artigo/súmula; sinalizar o que
precisa ser conferido; encerrar análises complexas lembrando que a resposta é apoio à atuação
profissional. Respostas em pt-BR.

### 5.2 Orquestração híbrida

- **Roteamento (maestro):** o Supervisor recebe a mensagem e, via **tool use** da Anthropic, decide
  entre responder direto (onboarding/conversa) ou delegar a um especialista. Cada especialista é uma
  *tool* (`consultar_notificacoes`, `consultar_peticoes`, ...). A resposta volta em streaming.
- **Atalho (advogado):** o front mantém os cards dos especialistas; clicar num card conversa direto.
- No M1 os especialistas **ainda não** têm memória do cliente (isso é M3+M4); respondem com seu
  conhecimento jurídico condominial. O gancho para consulta ao acervo já fica previsto na interface do
  agente para evitar retrabalho — é a fatia que dá o valor central depois.

### 5.3 Registro e API

- `app/services/chat.py`: `_REGISTRO` passa a conter Supervisor + 6 especialistas do escritório
  (substituindo os agentes genéricos atuais). `listar_agentes()` alimenta os cards.
- Endpoints reaproveitados: `GET /api/agentes`, `POST /api/chat` (streaming).
- Estado de onboarding conduzido pela conversa com o Supervisor no M1; persistência real na Espinha
  entra no M2 (no M1 pode ficar em sessão do front).

### 5.4 Frontend (M1)

Reaproveita `app/static/index.html` + `app.css`, re-tematizado para o escritório condominial:
- Tela inicial conduzida pelo Supervisor (primeiro contato/onboarding).
- Cards dos especialistas (atalho direto).
- Seletor de modelo mantido (Sonnet/Haiku/Opus).
- Placeholders (inertes no M1, ativados em M2/M3): seletor de **cliente (condomínio)** e **status da
  conexão Google**.
- Identidade sóbria/jurídica, responsiva, tema claro/escuro.

### 5.5 Testes (M1)

- `tests/test_chat_condominial.py`: registro dos 7 agentes; `obter_agente` para slugs válidos/inválidos;
  contrato do `/api/agentes`; roteamento do Supervisor (tool use mockado). Mocks da Anthropic com
  `unittest.mock`. Suíte verde (`uv run pytest`) e lint (`ruff`, `black`).

---

## 6. M2 — Espinha (roadmap)

Tabelas da seção 4 (migration em `sql/`), services de CRUD de condomínios/blocos/unidades/documentos,
e persistência do onboarding. Endpoints admin protegidos por `ADMIN_TOKEN` até integrar Supabase Auth.

## 7. M3 — Mãos / Google Drive via MCP (roadmap — valor central)

- **Conector MCP** para o Drive/Workspace (não chamadas soltas à API): os agentes acessam o acervo por
  ferramentas MCP. A plataforma também **expõe seus próprios endpoints MCP/API** para não ficar fechada
  a outras ferramentas.
- OAuth **modo teste** com a conta do escritório (escopo de leitura do Drive).
- **Dados na origem:** o acervo permanece no Drive do escritório; a plataforma guarda só índice +
  metadados + texto extraído. Sem duplicar arquivos.
- Convenção de pastas: `Condomínio X / Bloco A / Unidade 101 / (documentos)`; conteúdo pode estar
  desorganizado, o que importa é a hierarquia. O acervo real (link do Workspace fornecido pelo usuário)
  só é acessado por este fluxo autorizado — nunca por fora.
- **Ingestão automática:** o Supervisor varre o Drive, identifica cliente/data, classifica documentos
  por `categoria`, grava em `drive_index` + `documentos` e apresenta o resultado para confirmação
  humana — sem etapa manual de cadastro documento a documento.
- **Isolamento:** toda leitura é escopada ao `escritorio_id` (tenant) e ao `condominio_id` da demanda;
  nada de um cliente aparece para outro.
- Microsoft/OneDrive: conector futuro, mesmo contrato MCP.
- Passo-a-passo de configuração do Google Cloud entregue ao usuário nesta fase.

## 8. M4 — Memória (roadmap — "assertividade na leitura")

Antes de agir, o especialista: (1) identifica o condomínio; (2) puxa os `documentos` relevantes
(convenção, regimento, atas…) + `interacoes` anteriores; (3) lê sob demanda o conteúdo; (4) produz
seguindo o padrão do escritório. Cada tarefa concluída grava uma `interacao`. Evolução: extração de
texto + embeddings/pgvector para busca semântica no acervo.

---

## 9. Dependências externas (caminho crítico — responsabilidade do usuário)

1. 🔑 **ANTHROPIC_API_KEY** válida no `.env` (a atual retorna 401) — bloqueia qualquer resposta.
2. 🗄️ **Projeto Supabase** novo (URL + anon key + service role) — bloqueia M2+.
3. 🔐 **Projeto Google Cloud + OAuth** (consentimento em modo teste) — bloqueia M3+.

## 10. Não-objetivos (YAGNI por enquanto)

- Agentes voltados ao condomínio/síndico (Inadimplência, Assembleias, Convenção-como-produto).
- Portal do síndico (evolução futura).
- API de processos/andamentos (custosa — depois).
- Conectores Microsoft/OneDrive (mesmo contrato MCP, mas depois do Google).
- RAG com embeddings (evolução do M4).
- SaaS multi-escritório com onboarding self-service e verificação pública do app Google.
- Pagamentos/billing/mobile. O módulo de **Rifas** do repositório é **outro projeto**, sem relação.

## 11. Critérios de sucesso do MVP (sexta 17/07)

- Servidor sobe limpo; suíte de testes verde; lint limpo.
- Com chave Anthropic válida: Supervisor recebe o advogado, faz onboarding e **roteia** para os
  especialistas; cada especialista responde com conteúdo condominial correto e técnico.
- Front do escritório no ar com Supervisor + cards dos especialistas, seletor de cliente e status
  Google (inertes até M2/M3).
- Espinha (M2) e conexão Google (M3) na sequência, single-tenant, mirando a **fatia vertical** de
  demonstração para o Dr. Wilker (1 agente lendo o acervo real de 1 condomínio).
