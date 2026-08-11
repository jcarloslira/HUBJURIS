-- Migration 010 — Identidade visual (timbre) por escritório.
-- Guarda subtítulo (OAB/área), cor do timbre, rodapé de confidencialidade e o
-- logo (data URI base64, opcional). O nome do escritório já vem de escritorios.nome.

alter table public.escritorios
    add column if not exists branding jsonb not null default '{}'::jsonb;
