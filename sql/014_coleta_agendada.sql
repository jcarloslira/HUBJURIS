-- 014 — Coleta do EasyJur/Tiflux 3x por dia, agendada no próprio Supabase.
--
-- O EasyJur só guarda o ÚLTIMO andamento de cada processo: o de hoje apaga o de
-- ontem. Coletando três vezes por dia (7h, 12h30 e 18h30 em Brasília), nenhum
-- andamento se perde. O agendador é o pg_cron do Supabase, que não dorme como o
-- servidor gratuito do Render — a própria chamada acorda o Hub.
--
-- A chamada leva um token gerado AQUI, guardado no cofre (vault). O Hub confere
-- pela função lexhub_cron_confere, sem o segredo sair do banco.

select vault.create_secret(
    encode(extensions.gen_random_bytes(32), 'hex'),
    'lexhub_cron_token',
    'Token da coleta agendada do LexHub (pg_cron -> /api/gestao/cron)'
)
where not exists (select 1 from vault.secrets where name = 'lexhub_cron_token');

create or replace function public.lexhub_cron_confere(token text)
returns boolean
language sql
security definer
set search_path = ''
as $$
    select exists (
        select 1 from vault.decrypted_secrets
        where name = 'lexhub_cron_token' and decrypted_secret = token
    );
$$;

revoke all on function public.lexhub_cron_confere(text) from public, anon, authenticated;
grant execute on function public.lexhub_cron_confere(text) to service_role;

-- Reagenda do zero (idempotente). Horários em UTC: Brasília = UTC-3.
select cron.unschedule(jobname) from cron.job where jobname like 'lexhub-coleta-%';

select cron.schedule('lexhub-coleta-07h00', '0 10 * * *', $job$
    select net.http_post(
        url := 'https://hubjuris.onrender.com/api/gestao/cron',
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'X-Cron-Token', (select decrypted_secret from vault.decrypted_secrets
                             where name = 'lexhub_cron_token')
        ),
        body := '{}'::jsonb,
        timeout_milliseconds := 120000
    );
$job$);

select cron.schedule('lexhub-coleta-12h30', '30 15 * * *', $job$
    select net.http_post(
        url := 'https://hubjuris.onrender.com/api/gestao/cron',
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'X-Cron-Token', (select decrypted_secret from vault.decrypted_secrets
                             where name = 'lexhub_cron_token')
        ),
        body := '{}'::jsonb,
        timeout_milliseconds := 120000
    );
$job$);

select cron.schedule('lexhub-coleta-18h30', '30 21 * * *', $job$
    select net.http_post(
        url := 'https://hubjuris.onrender.com/api/gestao/cron',
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'X-Cron-Token', (select decrypted_secret from vault.decrypted_secrets
                             where name = 'lexhub_cron_token')
        ),
        body := '{}'::jsonb,
        timeout_milliseconds := 120000
    );
$job$);
