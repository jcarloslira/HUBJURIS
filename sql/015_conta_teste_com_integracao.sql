-- 015 — A conta de teste do Jean (Almeida Advogados) também usa EasyJur/Tiflux.
--
-- Pedido explícito do Jean em 11/09/2026: além do Jales (dono da conexão), SÓ a
-- conta de teste dele enxerga esses dados — é onde ele testa o que vai para o
-- Dr. Wilker. Qualquer outro escritório continua sem acesso (padrão false).

update public.escritorios
    set usa_easyjur_tiflux = true
    where nome ilike 'almeida advogados%';
