"""Molde fixo das peças do escritório — o visual dos relatórios do claude.ai.

Os relatórios que o sócio aprova (SQB e Casablanca, agosto/2026) foram gerados
no claude.ai com WeasyPrint 69.0. As medidas abaixo foram tiradas DE DENTRO
desses PDFs (cores, fontes, retângulos em px a 96 dpi), não a olho:

- página A4, margens 18 / 15 / 20 mm; capa sem margem, com faixa de 16 mm;
- corpo em Nimbus Sans 9,6 pt; títulos em Liberation Serif; títulos de cartão
  e números dos indicadores em DejaVu Serif;
- petróleo #1B3A3B / #2C5254, dourado #A79E6E, tinta #22292B, cinza #5E6B6D.

Por que um molde fixo em vez de o modelo escrever o CSS a cada peça: o CSS era
~40% dos tokens de saída (tempo e custo) e a fonte de todo defeito de layout —
cartão vazando, "Pág. 0", logo sumindo. Com a folha de estilo pronta e testada,
o modelo escreve só o conteúdo em HTML semântico, com as classes abaixo, e o
visual sai igual toda vez.
"""

from html import escape

from app.services.documentos import Timbre

# Paleta extraída dos PDFs aprovados.
PETROLEO_ESCURO = "#1B3A3B"
PETROLEO = "#2C5254"
DOURADO = "#A79E6E"
TINTA = "#22292B"
CINZA = "#5E6B6D"
CINZA_CLARO = "#8B9698"
BORDA = "#DFE3E1"
FUNDO = "#F4F6F5"

MARCADOR_LOGO = "__LOGO_DO_ESCRITORIO__"
# Cor que o timbre assume quando o escritório nunca escolheu uma (documentos.py).
COR_TIMBRE_PADRAO = "#9A6A3A"

_CSS = """
@page {
  size: A4;
  margin: 18mm 15mm 20mm 15mm;
  @bottom-left {
    content: "__RODAPE__";
    font: 7.2pt "Nimbus Sans", Helvetica, Arial, sans-serif;
    color: __CINZA_CLARO__;
  }
  @bottom-right {
    content: "pág. " counter(page) " / " counter(pages);
    font: 7.2pt "Nimbus Sans", Helvetica, Arial, sans-serif;
    color: __CINZA_CLARO__;
  }
}
@page capa {
  margin: 0;
  @bottom-left { content: none; }
  @bottom-right { content: none; }
}

* { box-sizing: border-box; }
html { font-family: "Nimbus Sans", Helvetica, Arial, sans-serif; font-size: 9.6pt;
       line-height: 1.5; color: __TINTA__; }
body { margin: 0; }
p { margin: 0 0 7pt; orphans: 3; widows: 3; }
b, strong { font-weight: bold; color: __TINTA__; }
em { font-style: italic; }
ul, ol { margin: 0 0 8pt; padding-left: 14pt; }
li { margin-bottom: 3pt; }

/* ---------- capa ---------- */
.capa { page: capa; position: relative; height: 297mm; padding: 0 22mm;
        break-after: page; }
.capa-faixa { position: absolute; top: 0; left: 0; right: 0; height: 16mm;
              background: __PETROLEO__; }
.capa-logo { display: block; position: absolute; top: 36mm; left: 22mm;
             max-width: 62mm; max-height: 46mm; }
.capa-corpo { position: absolute; top: 96mm; left: 22mm; right: 22mm; }
.capa-filete { width: 34mm; height: 2.2pt; background: __DOURADO__; margin-bottom: 7mm; }
.capa-kicker { font-size: 7.4pt; font-weight: bold; letter-spacing: 0.22em;
               text-transform: uppercase; color: __DOURADO__; margin: 0 0 4.5mm; }
.capa-titulo { font-family: "Liberation Serif", "Times New Roman", serif;
               font-size: 26pt; line-height: 1.12; font-weight: bold;
               color: __PETROLEO_ESCURO__; margin: 0 0 4mm; padding: 0; border: 0; }
.capa-sub { font-family: "DejaVu Serif", Georgia, serif; font-size: 12pt;
            color: __PETROLEO__; margin: 0; }
.capa-meta { margin: 15mm 0 0; padding-top: 5mm; border-top: 1px solid __BORDA__;
             font-size: 8pt; color: __CINZA__; }
.capa-meta p { margin: 0 0 2.6mm; }
.capa-meta b { color: __TINTA__; }
.capa-rodape { position: absolute; left: 0; right: 0; bottom: 0; height: 17.3mm;
               background: __FUNDO__; border-top: 4px solid __DOURADO__;
               padding: 6mm 22mm 0; font-size: 7.2pt; color: __CINZA__; }

/* ---------- títulos de seção ---------- */
h1, h2 { font-family: "Liberation Serif", "Times New Roman", serif; font-weight: bold;
         font-size: 15pt; line-height: 1.25; color: __PETROLEO_ESCURO__;
         margin: 16pt 0 4pt; padding-bottom: 5pt; border-bottom: 2pt solid __DOURADO__;
         break-after: avoid; }
h2:first-child, .quebra + h2 { margin-top: 0; }
h3 { font-family: "DejaVu Serif", Georgia, serif; font-weight: bold; font-size: 10.6pt;
     line-height: 1.35; color: __PETROLEO_ESCURO__; margin: 12pt 0 4pt; break-after: avoid; }
h4 { font-size: 8.4pt; font-weight: bold; color: __PETROLEO__; margin: 10pt 0 3pt;
     break-after: avoid; }
.lede { font-size: 7.6pt; color: __CINZA__; margin: 0 0 10pt; break-after: avoid; }
.nota { font-size: 7.2pt; color: __CINZA__; margin-top: -2pt; }
.quebra { break-before: page; height: 0; margin: 0; }

/* ---------- indicadores ---------- */
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin: 0 0 12pt;
        break-inside: avoid; }
.kpis.c2 { grid-template-columns: repeat(2, 1fr); }
.kpis.c3 { grid-template-columns: repeat(3, 1fr); }
.kpi { background: __FUNDO__; border-top: 2.5pt solid __PETROLEO__; padding: 8pt 9pt 9pt; }
.kpi b { display: block; font-family: "DejaVu Serif", Georgia, serif; font-weight: normal;
         font-size: 17pt; line-height: 1.15; color: __PETROLEO_ESCURO__; margin-bottom: 4pt; }
.kpi span { display: block; font-size: 6.8pt; letter-spacing: 0.06em;
            text-transform: uppercase; color: __CINZA__; line-height: 1.35; }
.kpi.vermelho { border-top-color: #8C3B2E; }
.kpi.verde { border-top-color: #3D6B4A; }
.kpi.dourado { border-top-color: #9A7A20; }

/* ---------- barras de distribuição ---------- */
/* Quantos de cada tipo, lado a lado: comparação que a tabela não dá de relance. */
.barras { margin: 0 0 12pt; break-inside: avoid; }
.barra { display: grid; grid-template-columns: 38mm 1fr 18mm; align-items: center;
         gap: 2.5mm; margin-bottom: 4pt; }
.barra .rot { font-size: 8.2pt; color: __TINTA__; }
.barra .trilho { background: #EAEFEE; height: 5mm; }
/* A largura vem por classe (p5…p100) porque estilo inline é removido do corpo. */
.barra .preenche { display: block; height: 5mm; background: __PETROLEO__; width: 0; }
__LARGURAS_BARRA__
.barra .val { text-align: right; font-size: 8pt; font-weight: bold;
              color: __PETROLEO_ESCURO__; }

/* ---------- tabela ---------- */
table { width: 100%; border-collapse: collapse; table-layout: auto; margin: 4pt 0 8pt;
        font-size: 8.6pt; line-height: 1.4; }
thead { display: table-header-group; }
th { background: __PETROLEO__; color: #FFFFFF; text-align: left; font-size: 7.4pt;
     font-weight: bold; letter-spacing: 0.04em; text-transform: uppercase;
     padding: 8pt 7pt; vertical-align: middle; }
td { padding: 7pt 7pt; border-bottom: 1px solid __BORDA__; vertical-align: top;
     word-wrap: break-word; }
tbody tr:nth-child(odd) td { background: #FAFBFA; }
tr { break-inside: avoid; }
td:first-child { font-weight: bold; }
td.num, th.num { text-align: right; white-space: nowrap; }
td small { font-size: 6.8pt; color: __CINZA__; font-weight: normal; }
table.simples td:first-child { font-weight: normal; }

/* ---------- alertas: o que exige decisão ---------- */
.alerta { background: #FDFBFA; border: 1px solid __BORDA__; border-left: 4px solid #8C3B2E;
          padding: 10pt 13pt 6pt; margin: 0 0 9pt; break-inside: avoid; font-size: 8.8pt; }
.alerta h3 { margin: 0 0 4pt; }
.alerta.media { background: #FDFCF7; border-left-color: #9A7A20; }
.alerta.baixa { background: #FBFCFB; border-left-color: __PETROLEO__; }
.selo { display: inline-block; background: #8C3B2E; color: #FFFFFF;
        font-family: "Nimbus Sans", Helvetica, sans-serif; font-size: 6.4pt;
        font-weight: bold; letter-spacing: 0.08em; text-transform: uppercase;
        padding: 1.6pt 6pt; border-radius: 7pt; margin-right: 4pt;
        vertical-align: 1.5pt; }
.media .selo { background: #9A7A20; }
.baixa .selo { background: __PETROLEO__; }

/* ---------- cartão de caso / processo ---------- */
.caso { background: #FBFCFB; border-left: 4px solid __DOURADO__; padding: 11pt 14pt 10pt;
        margin: 0 0 10pt; break-inside: avoid; font-size: 8.8pt; }
.caso.vermelho { border-left-color: #8C3B2E; }
.caso.verde { border-left-color: #3D6B4A; }
.caso.azul { border-left-color: __PETROLEO__; }
.caso h3 { margin: 0 0 2pt; }
.meta { font-size: 7.2pt; color: __CINZA_CLARO__; margin: 0 0 6pt; }
.tags { margin: 0 0 7pt; line-height: 1.9; }
.tag { display: inline-block; font-size: 6.6pt; letter-spacing: 0.05em;
       text-transform: uppercase; padding: 1.5pt 5.5pt; border-radius: 2pt;
       background: #E8EDEC; color: __PETROLEO__; margin-right: 3pt; }
.tag.vermelho { background: #F3E1DC; color: #8C3B2E; }
.tag.verde { background: #E1EDE4; color: #3D6B4A; }
.tag.dourado { background: #EFEBDA; color: #6B5F2E; }
.rotulo { font-size: 6.8pt; font-weight: bold; letter-spacing: 0.1em;
          text-transform: uppercase; color: __DOURADO__; margin: 7pt 0 2pt; }
.caso .rotulo:first-of-type { margin-top: 2pt; }
.proximo { background: #F1F4F3; border-left: 2pt solid __PETROLEO__; padding: 7pt 10pt;
           margin: 8pt 0 2pt; font-size: 8pt; }
.expl { background: #F6F4EC; border-left: 2pt solid __DOURADO__; padding: 7pt 10pt;
        margin: 7pt 0 2pt; font-size: 8pt; }
.expl b { display: block; font-size: 6.8pt; font-weight: bold; letter-spacing: 0.09em;
          text-transform: uppercase; color: #6B5F2E; margin-bottom: 2pt; }

/* ---------- linha do tempo ---------- */
.linha-tempo { list-style: none; margin: 4pt 0 10pt; padding: 0 0 0 4pt; }
.linha-tempo li { position: relative; padding: 0 0 8pt 16pt; margin: 0;
                  border-left: 1px solid __BORDA__; break-inside: avoid; font-size: 8.8pt; }
.linha-tempo li::before { content: ""; position: absolute; left: -4.5pt; top: 2pt;
                          width: 8pt; height: 8pt; border-radius: 4pt;
                          background: __PETROLEO__; }
.linha-tempo li.vermelho::before { background: #8C3B2E; }
.linha-tempo li.verde::before { background: #3D6B4A; }
.linha-tempo li.dourado::before { background: #9A7A20; }
.linha-tempo .quando { display: block; font-size: 7.2pt; font-weight: bold;
                       letter-spacing: 0.06em; text-transform: uppercase; color: __DOURADO__; }

/* ---------- citação e texto de peça ---------- */
blockquote { margin: 6pt 0 9pt; padding: 6pt 12pt; border-left: 2pt solid __DOURADO__;
             background: #FAFAF6; color: __TINTA__; font-size: 8.8pt; }
.peca p { text-align: justify; font-size: 10pt; line-height: 1.6; text-indent: 0; }
.assinatura { margin-top: 26pt; text-align: center; break-inside: avoid; }
.assinatura .linha { width: 70mm; margin: 0 auto 4pt; border-top: 1px solid __TINTA__; }

/* ---------- assinaturas do relatório ---------- */
/* Quem assina responde pelo envio: nome, OAB e o papel de cada um, lado a lado. */
.assinaturas { margin-top: 30pt; text-align: center; break-inside: avoid; }
.assinaturas .local { font-size: 8.6pt; color: __CINZA__; margin: 0 0 34pt; }
.assinaturas .colunas { display: flex; gap: 8mm; justify-content: center; }
.assinaturas .quem { flex: 0 0 72mm; }
.assinaturas .linha { border-top: 1px solid __TINTA__; margin: 0 auto 4pt; }
.assinaturas .nome { font-family: "DejaVu Serif", Georgia, serif; font-size: 9pt;
                     font-weight: bold; color: __PETROLEO_ESCURO__; white-space: nowrap; }
.assinaturas .oab { font-size: 8pt; color: __CINZA__; margin-top: 1.5pt; }
.assinaturas .papel { font-size: 7pt; font-weight: bold; text-transform: uppercase;
                      letter-spacing: 0.08em; color: __DOURADO__; margin-top: 4pt; }

/* ---------- fecho ---------- */
.fecho { background: __PETROLEO__; color: #E8EDEC; padding: 14pt 16pt 12pt;
         margin: 14pt 0 0; break-inside: avoid; font-size: 8.4pt; }
.fecho h3 { color: #FFFFFF; margin: 0 0 7pt; }
.fecho b, .fecho strong { color: #FFFFFF; }
.fecho .assinatura-fecho { margin: 10pt 0 0; padding-top: 7pt; font-size: 7.4pt;
                           border-top: 1px solid rgba(255, 255, 255, 0.22);
                           color: __DOURADO__; }
"""

_LARGURAS_BARRA = "\n".join(
    f".barra .preenche.p{n} {{ width: {n}%; }}" for n in range(5, 101, 5)
)

GUIA_COMPONENTES = """VOCABULÁRIO DE COMPONENTES (a folha de estilo já existe — use SÓ
estas classes, sem atributo style, sem <style>, sem CSS próprio)

CAPA — só se o pedido disser que você escreve a capa:
<section class="capa">
  <div class="capa-faixa"></div>
  __LOGO__
  <div class="capa-corpo">
    <div class="capa-filete"></div>
    <p class="capa-kicker">Relatório de acompanhamento processual</p>
    <h1 class="capa-titulo">Condomínio<br>Superquadra Brasília</h1>
    <p class="capa-sub">Análise dos 18 processos ativos · agosto de 2026</p>
    <div class="capa-meta">
      <p><b>Destinatário:</b> Síndico e Conselho</p>
      <p><b>Período analisado:</b> agosto de 2025 a agosto de 2026</p>
      <p><b>Data de emissão:</b> 17 de agosto de 2026</p>
      <p><b>Fontes:</b> capas, andamentos e publicações do sistema de gestão processual</p>
      <p><b>Elaboração:</b> Nome do Escritório</p>
    </div>
  </div>
  <div class="capa-rodape">Documento de uso interno do condomínio. Contém informações
  protegidas por sigilo profissional (art. 7º, II, da Lei 8.906/94).</div>
</section>

SEÇÃO:
<h2>1. Panorama geral</h2>
<p class="lede">Retrato da carteira em 17 de agosto de 2026, só processos ativos.</p>

INDICADORES (abra relatórios com 3 ou 4; classe c2/c3 para 2 ou 3 cartões):
<div class="kpis">
  <div class="kpi"><b>18</b><span>processos ativos</span></div>
  <div class="kpi"><b>R$ 218,8 mil</b><span>a receber em discussão</span></div>
</div>
Valores grandes no cartão vão abreviados (R$ 218,8 mil; R$ 1,2 mi).

TABELA (dado tabular; valores com class="num"; <small> para observação curta):
<table><thead><tr><th>Frente</th><th>Processos</th><th>Situação</th>
<th class="num">Valor</th></tr></thead>
<tbody><tr><td>Cobrança judicial <small>de unidades</small></td><td>7</td>
<td>Uma sentenciada, três em curso</td><td class="num">R$ 215.833,26</td></tr></tbody></table>
<p class="nota">Valores conforme cadastrados na capa de cada processo.</p>

ALERTA — "o que exige decisão ou atenção agora" (alta | media | baixa):
<div class="alerta alta"><h3><span class="selo">Alta</span>Trabalhista de R$ 437.959,67
voltou a andar em 11/08</h3><p>Processo 0001441-20.2025.5.10.0104. É a maior exposição
da carteira. <b>O ponto que decide</b> vai em negrito.</p></div>

CARTÃO DE CASO (um por processo/assunto; cor da barra = leitura: vermelho risco,
dourado neutro/em curso, verde favorável, azul informativo):
<div class="caso vermelho">
  <h3>Maria Gorete Candeira Gomes — a maior exposição da carteira</h3>
  <p class="meta">0001441-20.2025.5.10.0104 · 4ª Vara do Trabalho de Taguatinga
  · resp. Wilker Jales</p>
  <p class="tags"><span class="tag vermelho">Valor da causa: R$ 437.959,67</span>
  <span class="tag">Saneamento</span></p>
  <p class="rotulo">O que já foi feito</p><p>…</p>
  <p class="rotulo">Onde está agora</p><p>…</p>
  <p class="rotulo">Leitura franca</p><p>…</p>
  <div class="expl"><b>Por que o valor parece alto</b>Explicação que contextualiza o número,
  DENTRO do cartão a que se refere.</div>
  <div class="proximo"><b>Próximo passo:</b> acompanhar o saneamento e impugnar o laudo.</div>
</div>
Etiquetas: tag (neutra), tag vermelho, tag verde, tag dourado. Rótulos possíveis:
"O que aconteceu", "Onde está agora", "Do que se trata", "Leitura", "Trajetória",
"Pendência operacional" — escolha os que o caso pede, não todos.

BARRAS (distribuição por natureza, mesa ou frente; a maior fica com p100 e as
outras recebem a classe proporcional, de p5 a p100, de 5 em 5):
<div class="barras">
  <div class="barra"><span class="rot">Consultas e orientações</span>
  <span class="trilho"><span class="preenche p100"></span></span>
  <span class="val">136</span></div>
  <div class="barra"><span class="rot">Cobrança de cotas</span>
  <span class="trilho"><span class="preenche p35"></span></span>
  <span class="val">48</span></div>
</div>

LINHA DO TEMPO (marcos em ordem; li vermelho | verde | dourado para o estado):
<ul class="linha-tempo"><li class="verde"><span class="quando">abr 2022</span>
<b>Perícia favorável</b> — o laudo confirmou os vícios.</li></ul>

CITAÇÃO (lei, cláusula, trecho de decisão): <blockquote>…</blockquote>

PEÇA DE TEXTO CORRIDO (petição, notificação, parecer, contrato): envolva o corpo em
<div class="peca">…</div> — parágrafos justificados — e feche com
<div class="assinatura"><div class="linha"></div>Nome<br>OAB/UF 00.000</div>.

NÃO force quebra de página: a folha de estilo já não deixa título, cartão ou tabela
órfãos no fim da página. Quebra forçada deixa meia página em branco.

ASSINATURAS DO RELATÓRIO (depois do fecho; uma coluna por signatário — quem gerou
e envia vem SEMPRE primeiro):
<div class="assinaturas">
  <p class="local">Brasília/DF, 17 de setembro de 2026.</p>
  <div class="colunas">
    <div class="quem"><div class="linha"></div><div class="nome">NOME DO COLABORADOR</div>
    <div class="oab">OAB/DF 00.000</div><div class="papel">Responsável pelo relatório</div></div>
    <div class="quem"><div class="linha"></div><div class="nome">NOME DO PATRONO</div>
    <div class="oab">OAB/DF 00.000</div><div class="papel">Patrono da causa</div></div>
  </div>
</div>

FECHO (último bloco de relatórios):
<div class="fecho"><h3>Como ler este relatório</h3><p>…</p>
<p class="assinatura-fecho">Escritório · Cidade/UF · 17 de agosto de 2026</p></div>"""


def _cor_primaria(cor: str) -> str:
    """A cor da marca só substitui o petróleo se for escura o bastante.

    O timbre tem um marrom padrão para quem nunca escolheu cor, e há escritório
    que cadastra o dourado do logo como "cor da marca". Nos dois casos, trocar o
    petróleo deixaria a faixa da capa e o cabeçalho das tabelas claros demais
    para texto branco — o molde aprovado some.
    """
    valor = (cor or "").lstrip("#")
    if len(valor) != 6 or cor.upper() == COR_TIMBRE_PADRAO:
        return PETROLEO
    try:
        r, g, b = (int(valor[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return PETROLEO
    luminancia = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return f"#{valor.upper()}" if luminancia < 0.3 else PETROLEO


def css(timbre: Timbre) -> str:
    """Folha de estilo do molde, com o rodapé e a cor do escritório aplicados."""
    primaria = _cor_primaria(timbre.cor)
    rodape = f"{timbre.nome or 'Documento'} · Documento confidencial"
    trocas = {
        "__LARGURAS_BARRA__": _LARGURAS_BARRA,
        "__RODAPE__": rodape.replace("\\", "").replace('"', "'"),
        "__PETROLEO_ESCURO__": PETROLEO_ESCURO,
        "__PETROLEO__": primaria,
        "__DOURADO__": DOURADO,
        "__TINTA__": TINTA,
        "__CINZA_CLARO__": CINZA_CLARO,
        "__CINZA__": CINZA,
        "__BORDA__": BORDA,
        "__FUNDO__": FUNDO,
    }
    folha = _CSS
    for marcador, valor in trocas.items():
        folha = folha.replace(marcador, valor)
    return folha


def guia(timbre: Timbre) -> str:
    """Guia de componentes para o modelo, com o logo certo na capa de exemplo."""
    logo = f'<img class="capa-logo" src="{MARCADOR_LOGO}" alt="">' if timbre.logo else ""
    return GUIA_COMPONENTES.replace("__LOGO__", logo)


def montar_documento(corpo: str, *, titulo: str, timbre: Timbre) -> str:
    """Envolve o corpo escrito pelo modelo no documento HTML completo."""
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        f"<title>{escape(titulo)}</title><style>{css(timbre)}</style></head>"
        f"<body>{corpo}</body></html>"
    )
