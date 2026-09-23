-- 018 — O agente aprende com o escritório: regras ditas em conversa que passam a valer sempre.
--
-- As diretrizes (016) são o dossiê carregado de uma vez, por fora. O que faltava
-- era o aprendizado do DIA A DIA: o Dr. Wilker corrige uma vez ("não ponha seção
-- de agenda", "assine sempre com a OAB de quem gerou") e o Hub passa a fazer
-- assim em toda conversa seguinte, em qualquer sessão, sem ninguém repetir.
--
-- Duas portas, as duas gravando aqui:
--   • a ferramenta `aprender`, quando o agente reconhece a ordem na hora;
--   • o extrator de memória, que relê cada turno e captura a regra que passou batido.
--
-- `escopo` diz ONDE a regra vale: 'geral' (toda resposta) ou o slug do agente
-- ('peticoes', 'notificacoes', 'relatorio'…), para o prompt não carregar regra de
-- relatório quando o pedido é uma notificação.
--
-- RLS habilitado sem policies: acesso só pelo backend (service_role), como o resto.

create table if not exists public.aprendizados (
    id uuid primary key default gen_random_uuid(),
    escritorio_id uuid not null references public.escritorios (id) on delete cascade,
    escopo text not null default 'geral',
    regra text not null,
    motivo text,
    origem text not null default 'conversa' check (origem in ('conversa', 'ferramenta')),
    criado_por uuid,
    ativo boolean not null default true,
    vezes_aplicada integer not null default 0,
    created_at timestamptz not null default now(),
    atualizado_em timestamptz not null default now()
);

create index if not exists aprendizados_escritorio_idx
    on public.aprendizados (escritorio_id, ativo, escopo);

alter table public.aprendizados enable row level security;
