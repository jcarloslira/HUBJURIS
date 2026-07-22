-- ============================================================
-- Seed: Rifa Hilux Diesel 2024
-- ============================================================
-- Cadastra uma rifa estilo "site de sorteios" (referência RaspVip)
-- usando o mesmo modelo do projeto. Total 50.000 números,
-- R$ 9,99 por número, sorteio em ~30 dias.
--
-- Como rodar: cole no SQL Editor do Supabase ou via `supabase db push`
-- após mover para a pasta de migrations.
-- ============================================================

WITH nova_rifa AS (
    INSERT INTO rifas (
        titulo,
        subtitulo,
        descricao,
        imagem_url,
        preco_por_numero,
        total_numeros,
        data_sorteio,
        status,
        regulamento
    ) VALUES (
        'Toyota Hilux Diesel 2024',
        '0KM — Sorteio online',
        '(Descrição a ser preenchida pelo administrador)',
        NULL,
        9.99,
        50000,
        (NOW() + INTERVAL '30 days'),
        'ativa',
        '(Regulamento a ser preenchido pelo administrador)'
    )
    RETURNING id
),
numeros_inseridos AS (
    INSERT INTO numeros_rifa (rifa_id, numero, status)
    SELECT id, generate_series(0, 49999), 'disponivel'
    FROM nova_rifa
    RETURNING rifa_id
)
SELECT 'Rifa Hilux Diesel 2024 criada com sucesso!' AS mensagem,
       (SELECT id FROM nova_rifa) AS rifa_id,
       (SELECT COUNT(*) FROM numeros_inseridos) AS total_numeros;