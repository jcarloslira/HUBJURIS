-- 017 — Memória viva: o que foi pedido, o que foi feito e ONDE PAROU.
--
-- As conversas ficam no navegador de cada um; trocou de sessão, perdia o fio. A
-- tabela `interacoes` (criada vazia em 004) passa a ser a memória entre conversas:
-- depois de cada resposta, o Hub registra sozinho o assunto, onde a demanda parou
-- e o próximo passo, e devolve isso ao agente na conversa seguinte.

alter table public.interacoes
    add column if not exists user_id uuid,
    add column if not exists assunto text,
    add column if not exists onde_parou text,
    add column if not exists proximo_passo text;

create index if not exists interacoes_escritorio_data_idx
    on public.interacoes (escritorio_id, created_at desc);
create index if not exists interacoes_condominio_data_idx
    on public.interacoes (condominio_id, created_at desc);
