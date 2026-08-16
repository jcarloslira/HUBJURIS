-- Solta o freio dos agentes do LexHub.
--
-- Contexto: os agentes vinham travados em claude-sonnet-4-6 com max_tokens
-- baixíssimo (Supervisor em 2048 ≈ 1.400 palavras). Uma peça com timbre não
-- cabia, e o CHECK antigo (teto 8192) impedia qualquer correção pela tela de
-- admin. Os valores gravados aqui vencem os do código (app/services/chat.py
-- sobrescreve agente.model/max_tokens com a config do banco), então esta
-- migration é obrigatória — mexer só no Python não basta.

-- 1) Teto do CHECK: 8192 -> 64000 (alinhado com app/schemas/agentes.py).
alter table agentes_config drop constraint if exists agentes_config_max_tokens_check;

alter table agentes_config
  add constraint agentes_config_max_tokens_check
  check (max_tokens between 256 and 64000);

-- 2) Modelo e orçamento de saída por agente.
--    Redatores de peça (32k) x agentes de consulta (16k).
update agentes_config set modelo = 'claude-opus-5', max_tokens = 32000
 where slug = 'supervisor';

update agentes_config set modelo = 'claude-opus-5', max_tokens = 32000
 where slug = 'notificacoes';

update agentes_config set modelo = 'claude-opus-5', max_tokens = 32000
 where slug = 'peticoes';

update agentes_config set modelo = 'claude-opus-5', max_tokens = 32000
 where slug = 'contratos';

update agentes_config set modelo = 'claude-opus-5', max_tokens = 32000
 where slug = 'pareceres';

update agentes_config set modelo = 'claude-opus-5', max_tokens = 16000
 where slug = 'consulta-historica';

update agentes_config set modelo = 'claude-opus-5', max_tokens = 16000
 where slug = 'juridico-geral';

-- Conferência.
select slug, modelo, max_tokens from agentes_config order by ordem;
