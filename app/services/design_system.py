"""Sistema de design das peças do escritório, extraído dos relatórios aprovados.

Engenharia reversa dos 4 relatórios que o Dr. Wilker produz no claude.ai
(Casablanca, Águas Cristalinas, SQB e Loja 10), que compartilham exatamente a
mesma paleta, tipografia e gramática visual. As fontes embutidas (DejaVu Serif,
Nimbus Sans, Liberation Serif) denunciam a origem: HTML + CSS renderizados por
WeasyPrint num container Linux — o mesmo caminho que a Agent Skill ``pdf`` usa.
Por isso pedimos HTML/CSS ao modelo, e não desenho programático.

Editar este arquivo muda o visual de todas as peças novas.
"""

# Paleta idêntica nos 4 relatórios de referência.
PALETA = {
    "petroleo_escuro": "#1A3A3B",  # títulos de seção, faixa da capa
    "petroleo_medio": "#2B5254",  # cabeçalho de tabela, subtítulos
    "tinta": "#21282A",  # corpo do texto
    "cinza_secundario": "#5D6B6D",  # legendas, notas de tabela, metadados
    "dourado": "#A79E6E",  # kicker, filetes, marcadores de destaque
    "borda": "#DFE2E1",  # linhas de tabela e separadores
    "fundo_suave": "#F4F6F4",  # zebrado e caixas de destaque
}

ESPECIFICACAO = f"""SISTEMA DE DESIGN OBRIGATÓRIO

Gere o PDF escrevendo HTML + CSS e renderizando com WeasyPrint (é assim que as
peças aprovadas do escritório são feitas). Não desenhe o documento por
coordenadas.

PÁGINA
- A4 retrato, margens de 2cm; `@page` com rodapé em todas as páginas.
- Rodapé: "<nome do escritório> — Documento confidencial" à esquerda e
  "pág. X / N" à direita, em sans 8pt na cor {PALETA['cinza_secundario']},
  usando contadores CSS (`counter(page)` / `counter(pages)`).

PALETA (use exatamente estes valores)
- {PALETA['petroleo_escuro']} títulos de seção e faixa da capa
- {PALETA['petroleo_medio']} cabeçalho de tabela e subtítulos
- {PALETA['tinta']} corpo do texto
- {PALETA['cinza_secundario']} legendas, metadados e notas
- {PALETA['dourado']} kicker, filetes e marcadores de destaque
- {PALETA['borda']} bordas e separadores
- {PALETA['fundo_suave']} zebrado de tabela e caixas de destaque

TIPOGRAFIA
- Corpo: serifada ("DejaVu Serif", Georgia, serif) 10,5pt, entrelinha 1.5,
  parágrafos JUSTIFICADOS.
- Rótulos, números de KPI, cabeçalho de tabela, badges e rodapé: sans
  ("Nimbus Sans", Helvetica, Arial, sans-serif).
- Negrito seletivo dentro dos parágrafos para o dado que decide a leitura
  (valores, prazos, resultados). Nunca parágrafo inteiro em negrito.

CAPA (primeira página, sem rodapé)
1. Kicker em caixa alta, sans, letter-spacing largo, cor {PALETA['dourado']}
   (ex.: "RELATÓRIO DE ACOMPANHAMENTO PROCESSUAL").
2. Título grande serifado em {PALETA['petroleo_escuro']} (o nome do cliente),
   podendo ocupar duas linhas.
3. Deck de uma linha resumindo o escopo (ex.: "Análise dos 19 processos ativos
   — agosto de 2026").
4. Bloco de metadados em pares rótulo/valor: Destinatário, Período analisado,
   Data de emissão, Fonte dos dados, Elaboração.
5. Nota de confidencialidade em corpo menor citando o art. 7º, II, da Lei
   8.906/94.

SEÇÕES
- Numeradas ("1. Panorama geral"), em serifada bold {PALETA['petroleo_escuro']},
  precedidas de um filete fino {PALETA['dourado']}.
- Logo abaixo do título, uma linha de subtítulo em {PALETA['cinza_secundario']}
  explicando o recorte da seção.

COMPONENTES (use quando o conteúdo pedir)
- FAIXA DE INDICADORES: 3 a 4 números grandes em sans bold
  {PALETA['petroleo_escuro']} com rótulo pequeno em caixa alta embaixo
  (ex.: "19 / PROCESSOS ATIVOS"). Serve para abrir o panorama.
- TABELA: largura total, cabeçalho com fundo {PALETA['petroleo_medio']} e texto
  branco, linhas zebradas com {PALETA['fundo_suave']}, bordas
  {PALETA['borda']}, números alinhados à direita. Abaixo, nota explicativa em
  8,5pt {PALETA['cinza_secundario']}.
- BADGE DE SEVERIDADE: pequena etiqueta em caixa alta (ALTA / MÉDIA / BAIXA)
  antes do título do item, fundo sólido e texto branco.
- LINHA DO TEMPO: cada marco com bloco de data à direita ("28 SET / 2023") e um
  marcador colorido indicando o sentido — verde para favorável, vermelho para
  desfavorável, {PALETA['petroleo_escuro']} para ato da própria banca. Explique
  a legenda das cores antes da primeira ocorrência.
- CAIXA DE DESTAQUE: fundo {PALETA['fundo_suave']} com barra lateral
  {PALETA['dourado']} para alertas e conclusões.

FECHO
- Seção final "Como ler este relatório": 2 a 3 parágrafos de síntese em
  linguagem de sócio para cliente — o que está sob controle, o que exige
  decisão, e a colocação à disposição.
- Assinatura: "<escritório> — <cidade>/<UF> — <data por extenso>".

REGRAS DE OFÍCIO
- Valores em R$ no formato brasileiro (1.234,56); datas em dd/mm/aaaa.
- Todo dado numérico relevante vira tabela ou indicador, nunca lista corrida.
- Preserve integralmente acentos e pontuação do português.
- Evite quebra de página no meio de tabela ou de bloco de assinatura
  (`page-break-inside: avoid`).

CONFERÊNCIA FINAL (obrigatória)
Abra o PDF gerado e verifique página a página: nada cortado, sobreposto ou
vazando da margem; rodapé presente em todas as páginas exceto a capa; tabelas
inteiras. Se encontrar defeito, corrija o CSS e gere de novo."""
