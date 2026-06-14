-- ============================================================
-- Tabelas do módulo SDR (Superendividamento / Gestão de Passivo)
-- Executar no Supabase SQL Editor ou via migration CLI
-- ============================================================

-- Leads: contatos capturados pelo WhatsApp
CREATE TABLE IF NOT EXISTS leads (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    telefone TEXT UNIQUE NOT NULL,
    nome TEXT,
    tipo TEXT CHECK (tipo IN ('cpf', 'cnpj')),
    etapa_funil TEXT DEFAULT 'novo' CHECK (
        etapa_funil IN (
            'novo', 'em_qualificacao', 'qualificado',
            'agendado', 'convertido', 'descartado'
        )
    ),
    valor_divida NUMERIC,
    qtd_credores INTEGER,
    renda_mensal NUMERIC,
    tipos_divida TEXT[],
    observacoes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Mensagens SDR: histórico de conversa com cada lead
CREATE TABLE IF NOT EXISTS mensagens_sdr (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    direcao TEXT NOT NULL CHECK (direcao IN ('entrada', 'saida')),
    conteudo TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agendamentos: consultas marcadas
CREATE TABLE IF NOT EXISTS agendamentos (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    data_hora TIMESTAMPTZ NOT NULL,
    tipo TEXT DEFAULT 'online' CHECK (tipo IN ('presencial', 'online')),
    status TEXT DEFAULT 'confirmado' CHECK (
        status IN ('confirmado', 'cancelado', 'realizado')
    ),
    observacoes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Follow-ups: mensagens agendadas para envio futuro
CREATE TABLE IF NOT EXISTS follow_ups (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    tipo TEXT DEFAULT 'follow_up' CHECK (tipo IN ('lembrete', 'follow_up')),
    mensagem TEXT NOT NULL,
    data_agendada TIMESTAMPTZ NOT NULL,
    enviado BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Índices para performance ──────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_leads_telefone ON leads(telefone);
CREATE INDEX IF NOT EXISTS idx_leads_etapa ON leads(etapa_funil);
CREATE INDEX IF NOT EXISTS idx_mensagens_lead ON mensagens_sdr(lead_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agendamentos_lead ON agendamentos(lead_id);
CREATE INDEX IF NOT EXISTS idx_agendamentos_data ON agendamentos(data_hora);
CREATE INDEX IF NOT EXISTS idx_followups_pendentes
    ON follow_ups(data_agendada) WHERE enviado = FALSE;

-- ── RLS (Row Level Security) ──────────────────────────────────
-- Habilitar RLS nas tabelas para segurança
-- Políticas devem ser ajustadas conforme necessidade

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE mensagens_sdr ENABLE ROW LEVEL SECURITY;
ALTER TABLE agendamentos ENABLE ROW LEVEL SECURITY;
ALTER TABLE follow_ups ENABLE ROW LEVEL SECURITY;

-- Política para service_role (backend) — acesso total
CREATE POLICY "service_role_all_leads" ON leads
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all_mensagens" ON mensagens_sdr
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all_agendamentos" ON agendamentos
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all_followups" ON follow_ups
    FOR ALL USING (auth.role() = 'service_role');

-- Política para usuários autenticados (painel admin)
CREATE POLICY "auth_read_leads" ON leads
    FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "auth_read_mensagens" ON mensagens_sdr
    FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "auth_read_agendamentos" ON agendamentos
    FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "auth_read_followups" ON follow_ups
    FOR SELECT USING (auth.role() = 'authenticated');
