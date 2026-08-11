-- Migration 009 — Base de conhecimento (RAG) com pgvector + gte-small (384 dims).
-- Cada agente busca semanticamente trechos relevantes antes de responder.
-- Documentos globais da plataforma (escritorio_id NULL) valem para todos; documentos
-- com escritorio_id ficam isolados àquele escritório (multi-tenant).

create extension if not exists vector;

create table if not exists public.kb_documentos (
    id uuid primary key default gen_random_uuid(),
    escritorio_id uuid references public.escritorios (id) on delete cascade,
    titulo text not null,
    fonte text,                       -- slug estável: 'protocolo-stj', 'cpc', 'regimento'...
    categoria text,                   -- 'protocolo' | 'lei' | 'doutrina' | 'regimento' | 'modelo'
    total_chunks int not null default 0,
    criado_em timestamptz not null default now()
);

create table if not exists public.kb_chunks (
    id uuid primary key default gen_random_uuid(),
    documento_id uuid not null references public.kb_documentos (id) on delete cascade,
    escritorio_id uuid,               -- desnormalizado (NULL = global) p/ filtro rápido
    ordem int not null default 0,
    conteudo text not null,
    embedding vector (384),
    criado_em timestamptz not null default now()
);

-- Índice ANN (HNSW, cosseno) para busca rápida por similaridade.
create index if not exists kb_chunks_embedding_idx
    on public.kb_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists kb_chunks_escritorio_idx
    on public.kb_chunks (escritorio_id);
create index if not exists kb_chunks_documento_idx
    on public.kb_chunks (documento_id);

alter table public.kb_documentos enable row level security;
alter table public.kb_chunks enable row level security;

-- Busca semântica: trechos globais (escritorio_id NULL) + os do próprio escritório.
create or replace function public.kb_buscar (
    query_embedding vector (384),
    p_escritorio_id uuid default null,
    match_count int default 6
) returns table (
    conteudo text,
    titulo text,
    categoria text,
    similaridade float
) language sql stable as $$
    select
        c.conteudo,
        d.titulo,
        d.categoria,
        1 - (c.embedding <=> query_embedding) as similaridade
    from public.kb_chunks c
    join public.kb_documentos d on d.id = c.documento_id
    where c.embedding is not null
      and (c.escritorio_id is null or c.escritorio_id = p_escritorio_id)
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
