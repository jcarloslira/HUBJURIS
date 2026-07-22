-- 007 — Configuração dos agentes no banco (treinar/ajustar sem redeploy).
--
-- As instruções (system_prompt), o modelo e os limites de cada agente saem do
-- código e passam a viver aqui. Em runtime o hub lê esta tabela; o código só
-- fornece os PADRÕES (semeados no boot para agentes que ainda não existem na
-- tabela). Editar uma linha aqui muda o comportamento do agente na próxima
-- resposta — sem deploy.
--
-- Global (uma linha por agente, valendo para todos os escritórios). Overrides
-- por escritório podem vir depois com uma coluna escritorio_id.
--
-- RLS habilitado sem policies: acesso apenas via service_role (backend).

create table if not exists public.agentes_config (
    slug text primary key,
    nome text not null,
    descricao text not null default '',
    icone text not null default 'scale',
    system_prompt text not null,
    modelo text not null default 'claude-sonnet-4-6',
    max_tokens int not null default 1024 check (max_tokens between 256 and 8192),
    ativo boolean not null default true,
    ordem int not null default 0,
    updated_at timestamptz not null default now()
);

alter table public.agentes_config enable row level security;
