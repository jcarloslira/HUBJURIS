-- ============================================================
-- Tabelas do módulo de Rifas / Sorteios
-- Executar no Supabase SQL Editor ou via migration CLI
-- ============================================================

-- Rifas: cada sorteio ativo ou encerrado
CREATE TABLE IF NOT EXISTS rifas (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    titulo TEXT NOT NULL,
    subtitulo TEXT,
    descricao TEXT,
    imagem_url TEXT,
    preco_por_numero NUMERIC(10, 2) NOT NULL CHECK (preco_por_numero > 0),
    total_numeros INTEGER NOT NULL DEFAULT 100 CHECK (total_numeros > 0),
    data_sorteio TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'ativa' CHECK (
        status IN ('ativa', 'encerrada', 'sorteada', 'cancelada')
    ),
    numero_sorteado INTEGER,
    ganhador_nome TEXT,
    ganhador_telefone TEXT,
    regulamento TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Números de cada rifa (0..total_numeros-1). Status controla disponibilidade.
CREATE TABLE IF NOT EXISTS numeros_rifa (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    rifa_id UUID NOT NULL REFERENCES rifas(id) ON DELETE CASCADE,
    numero INTEGER NOT NULL CHECK (numero >= 0),
    status TEXT NOT NULL DEFAULT 'disponivel' CHECK (
        status IN ('disponivel', 'reservado', 'pago')
    ),
    pedido_id UUID,
    comprador_nome TEXT,
    comprador_telefone TEXT,
    comprador_email TEXT,
    reservado_ate TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (rifa_id, numero)
);

-- Pedidos: tentativa de compra de N números. Pode estar pendente, pago ou expirado.
CREATE TABLE IF NOT EXISTS pedidos_rifa (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    rifa_id UUID NOT NULL REFERENCES rifas(id) ON DELETE CASCADE,
    total_numeros INTEGER NOT NULL CHECK (total_numeros > 0),
    valor_total NUMERIC(10, 2) NOT NULL CHECK (valor_total > 0),
    comprador_nome TEXT NOT NULL,
    comprador_telefone TEXT NOT NULL,
    comprador_email TEXT,
    status TEXT NOT NULL DEFAULT 'pendente' CHECK (
        status IN ('pendente', 'pago', 'expirado', 'cancelado')
    ),
    mp_payment_id TEXT,
    mp_qr_code TEXT,
    mp_qr_code_base64 TEXT,
    mp_ticket_url TEXT,
    expires_at TIMESTAMPTZ,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vincular números ao pedido depois que o pedido é criado
ALTER TABLE numeros_rifa
    ADD CONSTRAINT fk_numeros_pedido
    FOREIGN KEY (pedido_id) REFERENCES pedidos_rifa(id) ON DELETE SET NULL;

-- ── Índices ───────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_rifas_status ON rifas(status, data_sorteio);
CREATE INDEX IF NOT EXISTS idx_numeros_rifa ON numeros_rifa(rifa_id, status);
CREATE INDEX IF NOT EXISTS idx_numeros_reservados
    ON numeros_rifa(reservado_ate) WHERE status = 'reservado';
CREATE INDEX IF NOT EXISTS idx_pedidos_rifa ON pedidos_rifa(rifa_id, created_at);
CREATE INDEX IF NOT EXISTS idx_pedidos_status
    ON pedidos_rifa(status, expires_at) WHERE status = 'pendente';
CREATE INDEX IF NOT EXISTS idx_pedidos_mp ON pedidos_rifa(mp_payment_id);

-- ── RLS ───────────────────────────────────────────────────────

ALTER TABLE rifas ENABLE ROW LEVEL SECURITY;
ALTER TABLE numeros_rifa ENABLE ROW LEVEL SECURITY;
ALTER TABLE pedidos_rifa ENABLE ROW LEVEL SECURITY;

-- service_role (backend) tem acesso total
CREATE POLICY "service_role_all_rifas" ON rifas
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all_numeros" ON numeros_rifa
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all_pedidos" ON pedidos_rifa
    FOR ALL USING (auth.role() = 'service_role');

-- Leitura pública das rifas ativas (catálogo) — anon pode listar rifas e números livres
CREATE POLICY "anon_read_rifas_ativas" ON rifas
    FOR SELECT USING (status IN ('ativa', 'encerrada', 'sorteada'));
CREATE POLICY "anon_read_numeros" ON numeros_rifa
    FOR SELECT USING (true);
