-- 016 — Como cada escritório trabalha (diretrizes fixas dos agentes).
--
-- A base semântica (009) responde "o que o escritório já decidiu sobre X". Mas
-- regra de ESTILO e de MÉTODO precisa valer em toda resposta, não só quando a
-- busca acerta o trecho: pedir "redija a peça" tem de sair no português do
-- escritório mesmo que a busca traga doutrina. Por isso as diretrizes entram no
-- prompt de todos os agentes daquele escritório, sempre.
--
-- O conteúdo (vindo do dossiê do ChatGPT, no caso do Jales) é carregado pelo
-- script scripts/importar_memoria_gpt.py --diretrizes.

alter table public.escritorios
    add column if not exists diretrizes text;
