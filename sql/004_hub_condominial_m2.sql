-- M2 (Espinha) — Hub de I.A Jurídico Condominial
-- Modelo de dados multi-tenant-ready: toda tabela de domínio carrega escritorio_id.
-- Acesso apenas pelo backend (service_role, que ignora RLS). RLS habilitada sem
-- políticas = bloqueada para anon/público; libera-se por política quando houver
-- Supabase Auth (SaaS). Estrutura: escritório → condomínios → blocos → unidades,
-- + índice do Drive, base documental por cliente e histórico de interações.

-- ---------------------------------------------------------------------------
-- Escritório (tenant). Hoje 1 linha; a coluna escritorio_id já entra em tudo.
-- ---------------------------------------------------------------------------
create table if not exists public.escritorios (
    id                uuid primary key default gen_random_uuid(),
    nome              text not null,
    site              text,
    instagram         text,
    google_conectado  boolean not null default false,
    created_at        timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Condomínios (clientes do escritório)
-- ---------------------------------------------------------------------------
create table if not exists public.condominios (
    id               uuid primary key default gen_random_uuid(),
    escritorio_id    uuid not null references public.escritorios(id) on delete cascade,
    nome             text not null,
    cnpj             text,
    endereco         text,
    drive_folder_id  text,
    status           text not null default 'ativo',
    created_at       timestamptz not null default now()
);
create index if not exists idx_condominios_escritorio on public.condominios(escritorio_id);

-- ---------------------------------------------------------------------------
-- Blocos de um condomínio
-- ---------------------------------------------------------------------------
create table if not exists public.blocos (
    id               uuid primary key default gen_random_uuid(),
    condominio_id    uuid not null references public.condominios(id) on delete cascade,
    nome             text not null,
    drive_folder_id  text,
    created_at       timestamptz not null default now()
);
create index if not exists idx_blocos_condominio on public.blocos(condominio_id);

-- ---------------------------------------------------------------------------
-- Unidades de um bloco
-- ---------------------------------------------------------------------------
create table if not exists public.unidades (
    id               uuid primary key default gen_random_uuid(),
    bloco_id         uuid not null references public.blocos(id) on delete cascade,
    identificacao    text not null,
    drive_folder_id  text,
    created_at       timestamptz not null default now()
);
create index if not exists idx_unidades_bloco on public.unidades(bloco_id);

-- ---------------------------------------------------------------------------
-- Espelho estrutural das pastas do Drive (condomínio/bloco/unidade/pasta)
-- ---------------------------------------------------------------------------
create table if not exists public.drive_index (
    id               uuid primary key default gen_random_uuid(),
    escritorio_id    uuid not null references public.escritorios(id) on delete cascade,
    drive_file_id    text not null,
    tipo             text not null check (tipo in ('condominio', 'bloco', 'unidade', 'pasta')),
    condominio_id    uuid references public.condominios(id) on delete cascade,
    nome             text,
    caminho          text,
    modified_at      timestamptz,
    synced_at        timestamptz not null default now()
);
create index if not exists idx_drive_index_escritorio on public.drive_index(escritorio_id);
create index if not exists idx_drive_index_condominio on public.drive_index(condominio_id);
create unique index if not exists uq_drive_index_file on public.drive_index(escritorio_id, drive_file_id);

-- ---------------------------------------------------------------------------
-- Base de conhecimento por cliente: documentos classificados por categoria
-- ---------------------------------------------------------------------------
create table if not exists public.documentos (
    id               uuid primary key default gen_random_uuid(),
    escritorio_id    uuid not null references public.escritorios(id) on delete cascade,
    condominio_id    uuid references public.condominios(id) on delete cascade,
    categoria        text not null check (categoria in (
        'convencao', 'regimento', 'ata', 'deliberacao', 'contrato', 'peticao',
        'notificacao', 'parecer', 'acordo', 'historico', 'outro'
    )),
    drive_file_id    text,
    nome             text,
    caminho          text,
    mime             text,
    modified_at      timestamptz,
    texto_extraido   text,
    synced_at        timestamptz not null default now()
);
create index if not exists idx_documentos_condominio on public.documentos(condominio_id);
create index if not exists idx_documentos_condominio_categoria
    on public.documentos(condominio_id, categoria);

-- ---------------------------------------------------------------------------
-- Histórico de interações: o que cada agente fez para cada condomínio.
-- Fonte do "seguir o padrão anterior".
-- ---------------------------------------------------------------------------
create table if not exists public.interacoes (
    id                uuid primary key default gen_random_uuid(),
    escritorio_id     uuid not null references public.escritorios(id) on delete cascade,
    condominio_id     uuid references public.condominios(id) on delete set null,
    agente            text not null,
    pedido            text,
    resultado_resumo  text,
    documento_gerado  text,
    created_at        timestamptz not null default now()
);
create index if not exists idx_interacoes_escritorio on public.interacoes(escritorio_id);
create index if not exists idx_interacoes_condominio on public.interacoes(condominio_id);

-- ---------------------------------------------------------------------------
-- RLS: habilitada em tudo. Sem políticas => somente service_role (backend)
-- acessa; anon/público fica bloqueado. Políticas por tenant entram com o
-- Supabase Auth na evolução para SaaS.
-- ---------------------------------------------------------------------------
alter table public.escritorios  enable row level security;
alter table public.condominios  enable row level security;
alter table public.blocos       enable row level security;
alter table public.unidades     enable row level security;
alter table public.drive_index  enable row level security;
alter table public.documentos   enable row level security;
alter table public.interacoes   enable row level security;
