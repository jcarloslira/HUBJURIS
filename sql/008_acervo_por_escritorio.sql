-- 008 — Acervo do Drive por escritório (Composio multi-tenant).
--
-- Cada escritório conecta o PRÓPRIO Google Drive (a identidade no Composio é o
-- escritorio_id) e escolhe qual pasta é o acervo de modelos. Guardamos aqui a
-- pasta escolhida; a conexão em si é gerenciada pelo Composio (checada ao vivo).

alter table public.escritorios
    add column if not exists acervo_folder_id text;
