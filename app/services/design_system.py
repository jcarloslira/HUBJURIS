"""Sistema de design das peças do escritório.

Duas gerações de referência foram estudadas: os relatórios em WeasyPrint que o
sócio já aprovava (paleta petróleo/dourado, tipografia editorial) e a geração
seguinte, feita no claude.ai, que é o alvo atual — 41 retângulos na primeira
página contra 7 dos nossos. A diferença não é gosto: o relatório novo **traduz
informação em componente visual** (cartão, etiqueta, marcador de linha do tempo)
em vez de empilhar parágrafo e tabela, e por isso cabe em 4 páginas o que antes
levava 7.

Editar este arquivo muda o visual de todas as peças novas.
"""

# Identidade do escritório (o timbre pode sobrepor o petróleo pela cor da marca).
PALETA = {
    "petroleo_escuro": "#1A3A3B",
    "petroleo_medio": "#2B5254",
    "tinta": "#21282A",
    "cinza_secundario": "#5D6B6D",
    "dourado": "#A79E6E",
    "borda": "#DFE2E1",
    "fundo_suave": "#F4F6F4",
}

# Cores de estado — o que dá leitura instantânea ao documento.
SEMANTICA = {
    "favoravel": "#2D692D",
    "favoravel_fundo": "#E2F4E2",
    "desfavoravel": "#A32D2D",
    "desfavoravel_fundo": "#F9E8E8",
    "atencao": "#794F00",
    "atencao_fundo": "#FFF2CC",
    "informacao": "#185EA5",
    "informacao_fundo": "#DBE8F7",
}

ESPECIFICACAO = f"""SISTEMA DE DESIGN OBRIGATÓRIO

Escreva HTML + CSS; o WeasyPrint renderiza. Não desenhe por coordenadas.

PRINCÍPIO QUE MANDA EM TUDO
O documento é um PAINEL DE LEITURA RÁPIDA, não um texto corrido. Toda informação
que puder virar componente visual (cartão, etiqueta, marcador, ícone) DEVE virar.
Parágrafo só para análise que exige argumentação. Prefira 4 páginas densas e
visuais a 7 páginas de prosa: se uma seção virou três parágrafos seguidos sem
nenhum componente, ela está errada — reescreva como cartões ou lista com ícone.

PÁGINA
- A4, margens 1,8cm. A área útil é de 17,4cm — TUDO tem de caber nela.
- Cabeçalho corrido da 2ª página em diante (NUNCA na capa):
  "<escritório> · Documento Confidencial · Pág. X", sans 8pt,
  {PALETA['cinza_secundario']}, com filete fino embaixo. Use `@page` com
  `counter(page)` e uma `@page :first` sem cabeçalho — a capa não é paginada e
  nunca deve exibir "Pág. 0".
- Nada de quebra dentro de cartão, tabela ou assinatura (`page-break-inside: avoid`).

LARGURA — REGRA QUE NÃO PODE SER VIOLADA
Cartão vazando da margem é o defeito mais comum e corta texto no papel. Portanto:
- `*{{ box-sizing: border-box; }}` obrigatório.
- Grids com `display: grid` + `grid-template-columns: repeat(N, 1fr)` e `gap`;
  NUNCA largura fixa em px/cm nas colunas, nunca `width` maior que 100%.
- Cartões de indicador: no máximo 4 colunas (conteúdo curto).
- Cartões de prioridade e qualquer cartão com parágrafo: NO MÁXIMO 2 COLUNAS —
  em 3 colunas o texto não cabe em A4 e é cortado.
- Tabela sempre `width: 100%` com `table-layout: fixed` e `word-wrap: break-word`.

PALETA INSTITUCIONAL
- {PALETA['petroleo_escuro']} títulos e faixa da capa
- {PALETA['petroleo_medio']} cabeçalho de tabela
- {PALETA['tinta']} corpo
- {PALETA['cinza_secundario']} rótulos, metadados e notas
- {PALETA['dourado']} kicker e filetes
- {PALETA['borda']} bordas · {PALETA['fundo_suave']} fundo de cartão

CORES DE ESTADO (dão a leitura instantânea — use sempre que houver juízo de valor)
- Favorável: texto {SEMANTICA['favoravel']} sobre {SEMANTICA['favoravel_fundo']}
- Desfavorável/urgente: {SEMANTICA['desfavoravel']} sobre {SEMANTICA['desfavoravel_fundo']}
- Atenção/prazo: {SEMANTICA['atencao']} sobre {SEMANTICA['atencao_fundo']}
- Informação/andamento neutro: {SEMANTICA['informacao']} sobre {SEMANTICA['informacao_fundo']}

TIPOGRAFIA
- Corpo: "DejaVu Serif", Georgia, serif — 10pt, entrelinha 1.45, justificado.
- Rótulos, números, etiquetas, cabeçalhos e ícones: "Nimbus Sans", Helvetica,
  sans-serif. Rótulo de cartão em CAIXA ALTA, 7,5pt, letter-spacing 0.08em.
- Negrito só no dado que decide a leitura (valor, prazo, resultado).

CAPA (primeira página)
Kicker dourado em caixa alta → nome do cliente em serifa grande → identificação
(CNPJ · cidade/UF) → duas linhas de contexto (período coberto; data de emissão ·
fonte dos dados · tamanho do acervo).

FAIXA DE ALERTA (logo abaixo da capa, quando houver urgência)
Uma linha em fundo {SEMANTICA['desfavoravel_fundo']} com barra lateral
{SEMANTICA['desfavoravel']}: "N ações urgentes identificadas nesta semana —
prioridades detalhadas na seção abaixo."

CARTÃO DE INDICADOR — obrigatório abrir o relatório com 3 a 4 destes, em linha
Três níveis empilhados, cada cartão com borda {PALETA['borda']} e fundo branco:
  1. rótulo em caixa alta ({PALETA['cinza_secundario']}, 7,5pt)
  2. número grande (sans bold, 26pt, {PALETA['petroleo_escuro']})
  3. descrição curta em 8pt ({PALETA['cinza_secundario']}) — ex.: "em tramitação",
     "quitados / acordados", "7 páginas verificadas"

CARTÕES DE PRIORIDADE — para "o que exige decisão agora"
Grid de até 3 colunas. Cada cartão traz:
  - etiqueta superior colorida por urgência: "Prioridade 1 — urgente"
    (vermelho), "Prioridade 2 — esta semana" (âmbar), etc.
  - título da PROVIDÊNCIA em negrito (o verbo primeiro: "Iniciar cumprimento de
    sentença", "Protocolar petição inicial")
  - 2 a 3 linhas dizendo POR QUE agora e o que se perde se não fizer
  - número do processo no rodapé do cartão, em mono/sans 7,5pt

DESTAQUE DE PROCESSO CRÍTICO
Bloco com título "Processo crítico — R$ valor", número do processo, linha de
identificação (partes · vara · valor) e uma etiqueta de estado
("Posição favorável" em verde, "Risco de extinção" em vermelho).

LINHA DO TEMPO
Marcador ● colorido pelo estado + período à esquerda ("abr 2022", "27 ago 2026")
+ título do marco em negrito + 1 a 2 linhas de descrição. O último marco é o
momento presente, rotulado "— agora", em vermelho/âmbar, dizendo a ação requerida.

LISTA DE MOVIMENTAÇÕES (não use tabela para isso)
Cada item é uma linha com: ícone semântico à esquerda (✓ favorável, ■ andamento
neutro, ⚠ prazo/risco, ✉ comunicação enviada), título em negrito, data à direita
em sans 8pt, descrição de 1 a 2 linhas embaixo e o número do processo em
{PALETA['cinza_secundario']} 7,5pt fechando o item. Separe por filete
{PALETA['borda']}.

TABELA (só para dado realmente tabular, como quadro de débitos)
Cabeçalho {PALETA['petroleo_medio']} com texto branco, zebrado
{PALETA['fundo_suave']}, bordas {PALETA['borda']}, números à direita, nota
explicativa em 8pt embaixo.

FECHO
Seção "Como ler este relatório": 2 a 3 parágrafos de sócio para cliente — o que
está sob controle, o que exige decisão, colocação à disposição. Assinatura:
"<escritório> — <cidade>/<UF> — <data por extenso>".

REGRAS DE OFÍCIO
- Valores em R$ no padrão brasileiro (1.234,56); datas em dd/mm/aaaa.
- Preserve integralmente acentos e pontuação do português.
- Nunca invente dado. E não polua a peça com ausências: se um campo não veio na
  fonte (número do processo, vara, valor), OMITA a linha inteira em vez de
  escrever "não informado". Só registre a ausência quando ela for, em si, o
  achado (ex.: "processo sem número CNJ cadastrado").

LOGOTIPO
O logotipo do escritório é colorido e feito para fundo claro. Coloque-o SEMPRE
sobre fundo branco ou muito claro — se a capa tiver fundo escuro, ou use a capa
clara, ou apoie o logotipo numa faixa/retângulo branco com respiro ao redor.
Nunca o coloque direto sobre cor escura: ele some."""
