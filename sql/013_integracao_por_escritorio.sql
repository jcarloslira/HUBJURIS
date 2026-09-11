-- 013 — EasyJur/Tiflux pertencem a UM escritório.
--
-- A chave do mcp.ai configurada no servidor é a do Jales & Jales. Sem esta
-- marcação, qualquer conta logada consultava esses sistemas pelo chat e, com a
-- coleta diária (012), importava os clientes do Jales para a própria carteira.
-- Agora só o escritório marcado aqui consulta e coleta.

alter table public.escritorios
    add column if not exists usa_easyjur_tiflux boolean not null default false;

update public.escritorios
    set usa_easyjur_tiflux = true
    where nome ilike 'jales%';
