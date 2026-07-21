-- Multi-tenant: membros do escritório (vinculados ao Supabase Auth) e medição de uso.
-- Aplicada no projeto ddsvxbdmrmktwfgrtbfq em 2026-07-14 (migration auth_membros_uso_tokens).

create table if not exists public.membros (
    user_id        uuid primary key,
    escritorio_id  uuid not null references public.escritorios(id) on delete cascade,
    nome           text not null,
    email          text not null,
    papel          text not null default 'admin' check (papel in ('admin', 'advogado', 'estagiario')),
    created_at     timestamptz not null default now()
);
create index if not exists idx_membros_escritorio on public.membros(escritorio_id);
create unique index if not exists uq_membros_email on public.membros(email);

create table if not exists public.uso_tokens (
    id              uuid primary key default gen_random_uuid(),
    escritorio_id   uuid references public.escritorios(id) on delete cascade,
    user_id         uuid,
    agente          text,
    modelo          text,
    tokens_entrada  integer not null default 0,
    tokens_saida    integer not null default 0,
    created_at      timestamptz not null default now()
);
create index if not exists idx_uso_escritorio_data on public.uso_tokens(escritorio_id, created_at);

-- RLS ligada, sem políticas => acesso apenas pelo backend (service_role).
alter table public.membros    enable row level security;
alter table public.uso_tokens enable row level security;
