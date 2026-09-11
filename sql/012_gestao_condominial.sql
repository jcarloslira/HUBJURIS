-- 012 — Gestão condominial no Hub: cadastro vinculado, diário de eventos e foto do dia.
--
-- O Hub passa a guardar, dia após dia, tudo o que acontece com cada condomínio no
-- EasyJur (processo novo, andamento, encerramento) e no Tiflux (ticket aberto,
-- ticket encerrado). Com isso os relatórios de qualquer período saem do NOSSO
-- banco, em milissegundos, e a história não se perde quando o EasyJur sobrescreve
-- o "último andamento" de um processo.
--
--   1. condominios          → vínculo com EasyJur/Tiflux + dados de gestão
--   2. eventos_condominio   → o diário (idempotente pela coluna `chave`)
--   3. fotos_diarias        → retrato de cada condomínio em cada dia
--   4. sincronizacoes       → registro de cada coleta
--
-- RLS habilitado sem policies: acesso só pelo backend (service_role), como o resto.

alter table public.condominios
    add column if not exists easyjur_cliente_id text,
    add column if not exists tiflux_cliente_id text,
    add column if not exists sindico text,
    add column if not exists administradora text,
    add column if not exists cidade text,
    add column if not exists uf text,
    add column if not exists observacoes text,
    add column if not exists origem text not null default 'manual',
    add column if not exists atualizado_em timestamptz not null default now();

create unique index if not exists condominios_easyjur_uidx
    on public.condominios (escritorio_id, easyjur_cliente_id);
create unique index if not exists condominios_tiflux_uidx
    on public.condominios (escritorio_id, tiflux_cliente_id);

-- O diário. `chave` identifica o fato (ex.: "ej:and:123:2026-09-10:ab12cd"), então
-- coletar o mesmo dia duas vezes não duplica nada.
create table if not exists public.eventos_condominio (
    id uuid primary key default gen_random_uuid(),
    escritorio_id uuid not null references public.escritorios (id) on delete cascade,
    condominio_id uuid references public.condominios (id) on delete set null,
    fonte text not null check (fonte in ('easyjur', 'tiflux', 'hub')),
    tipo text not null,
    chave text not null,
    referencia text,
    titulo text not null,
    descricao text,
    valor numeric(14, 2),
    ocorrido_em date not null,
    dados jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create unique index if not exists eventos_condominio_chave_uidx
    on public.eventos_condominio (escritorio_id, chave);
create index if not exists eventos_condominio_dia_idx
    on public.eventos_condominio (escritorio_id, ocorrido_em desc);
create index if not exists eventos_condominio_condominio_idx
    on public.eventos_condominio (condominio_id, ocorrido_em desc);

-- Retrato do dia: quantos processos ativos, quanto em causa, quantos tickets
-- abertos. A série destes retratos é a evolução do condomínio ao longo dos anos.
create table if not exists public.fotos_diarias (
    condominio_id uuid not null references public.condominios (id) on delete cascade,
    dia date not null,
    escritorio_id uuid not null references public.escritorios (id) on delete cascade,
    processos_ativos integer not null default 0,
    processos_total integer not null default 0,
    valor_causas_ativas numeric(14, 2) not null default 0,
    tickets_abertos integer not null default 0,
    dados jsonb not null default '{}'::jsonb,
    primary key (condominio_id, dia)
);

create index if not exists fotos_diarias_escritorio_dia_idx
    on public.fotos_diarias (escritorio_id, dia desc);

create table if not exists public.sincronizacoes (
    id uuid primary key default gen_random_uuid(),
    escritorio_id uuid not null references public.escritorios (id) on delete cascade,
    dia date not null,
    status text not null default 'rodando' check (status in ('rodando', 'ok', 'erro')),
    iniciada_em timestamptz not null default now(),
    concluida_em timestamptz,
    resumo jsonb not null default '{}'::jsonb,
    erro text
);

create index if not exists sincronizacoes_escritorio_idx
    on public.sincronizacoes (escritorio_id, iniciada_em desc);

alter table public.eventos_condominio enable row level security;
alter table public.fotos_diarias enable row level security;
alter table public.sincronizacoes enable row level security;
