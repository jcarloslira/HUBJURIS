-- 006 — Projetos (condomínios) multi-tenant: memória por projeto e auditoria de ações.
--
-- O "Projeto" do hub é o próprio condomínio (tabela `condominios`, já com
-- escritorio_id). Aqui adicionamos:
--   1. condominio_fatos  → memória curável por projeto (fatos que o agente aprende)
--   2. acoes_agente      → trilha de auditoria de tudo que os agentes executam
--   3. índice único      → idempotência do auto-registro de condomínio por escritório
--
-- RLS habilitado sem policies: acesso apenas via service_role (backend), igual
-- ao restante do schema multi-tenant.

-- Memória por condomínio (projeto): fatos aprendidos, revisáveis pelo advogado.
create table if not exists public.condominio_fatos (
    id uuid primary key default gen_random_uuid(),
    condominio_id uuid not null references public.condominios (id) on delete cascade,
    escritorio_id uuid not null references public.escritorios (id) on delete cascade,
    fato text not null,
    origem text not null default 'agente',  -- 'agente' | 'manual'
    created_at timestamptz not null default now()
);

create index if not exists condominio_fatos_condominio_idx
    on public.condominio_fatos (condominio_id);
create index if not exists condominio_fatos_escritorio_idx
    on public.condominio_fatos (escritorio_id);

-- Trilha de auditoria: cada ação que um agente executa no sistema fica registrada.
create table if not exists public.acoes_agente (
    id uuid primary key default gen_random_uuid(),
    escritorio_id uuid not null references public.escritorios (id) on delete cascade,
    user_id uuid,
    agente text not null default 'supervisor',
    ferramenta text not null,
    argumentos jsonb not null default '{}'::jsonb,
    resultado text,
    created_at timestamptz not null default now()
);

create index if not exists acoes_agente_escritorio_idx
    on public.acoes_agente (escritorio_id);

-- Unicidade case-insensitive do condomínio por escritório: o auto-registro do
-- agente vira idempotente (mesmo nome → mesmo projeto, sem duplicar).
create unique index if not exists condominios_escritorio_nome_uidx
    on public.condominios (escritorio_id, lower(nome));

alter table public.condominio_fatos enable row level security;
alter table public.acoes_agente enable row level security;
