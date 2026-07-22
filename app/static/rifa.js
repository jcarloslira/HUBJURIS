/* =============================================================
   Página da rifa — seleção de números e checkout
   ============================================================= */

const params = new URLSearchParams(location.search);
// Suporta três formas: ?id=<uuid>, ?slug=<slug>, ou /rifas/<slug> direto no path
const pathSlug = (() => {
  const m = location.pathname.match(/^\/rifas\/([^/?#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
})();
const RIFA_ID = params.get('id') || params.get('slug') || pathSlug || 'demo-1';

const state = {
  rifa: null,
  numeros: null,
  selected: new Set(),
  qty: 1,
  countdownTimer: null,
};

// ---------- carregar rifa ----------
async function load() {
  try {
    const [rifa, numeros] = await Promise.all([
      api.obterRifa(RIFA_ID),
      api.listarNumeros(RIFA_ID),
    ]);
    state.rifa = rifa;
    state.numeros = numeros;
    document.title = rifa.titulo + ' — RifaVIP';
    render();
    bind();
    // Atualiza countdown a cada minuto
    state.countdownTimer = setInterval(updateCountdown, 60000);
    // Escuta confirmação de pagamento (modo demo)
    window.addEventListener('demo:pagamento', onPagamentoDemo);
  } catch (e) {
    document.querySelector('.page-rifa').innerHTML = `
      <div class="empty" style="padding:80px 20px">
        <span class="big-emoji">😕</span>
        Rifa não encontrada.<br>
        <a href="/rifas" class="btn btn-gradient" style="margin-top:16px;display:inline-flex">Voltar aos sorteios</a>
      </div>`;
  }
}

function render() {
  const r = state.rifa;
  // imagem real quando houver, senão emoji
  if (r.imagem_url) {
    document.getElementById('hero-photo').style.backgroundImage = `url('${r.imagem_url}')`;
    document.getElementById('hero-photo').style.display = 'block';
    document.getElementById('hero-emoji').style.display = 'none';
  } else {
    document.getElementById('hero-emoji').textContent = r.imagem_emoji || '🎁';
  }
  document.getElementById('hero-titulo').textContent = r.titulo;
  document.getElementById('hero-sub').textContent = r.subtitulo || '';
  document.getElementById('hero-pill').textContent = r.status === 'sorteada' ? '🏆 SORTEADA' : (r.status === 'ativa' ? '🟢 AO VIVO' : '⏸ ENCERRADA');
  document.getElementById('info-data').textContent = fmtDate(r.data_sorteio);
  document.getElementById('info-preco').textContent = fmtBRL(r.preco_por_numero);
  document.getElementById('descricao').textContent = r.descricao || '';
  updateProgress();
  renderNumbers();
  updateTotal();
}

function updateCountdown() {
  if (!state.rifa) return;
  const remaining = countdown(state.rifa.data_sorteio);
  const pill = document.getElementById('hero-pill');
  if (pill && remaining === 'Encerrado') pill.textContent = '🏁 ENCERRADO';
}

function updateProgress() {
  const r = state.rifa, n = state.numeros;
  document.getElementById('prog-vendidos').textContent = `${n.pagos}/${n.total}`;
  const pct = Math.round((n.pagos / n.total) * 100);
  document.getElementById('prog-pct').textContent = pct + '%';
  document.getElementById('prog-bar').style.width = pct + '%';
}

function renderNumbers() {
  const grid = document.getElementById('numbers-grid');
  grid.innerHTML = '';
  const max = Math.min(state.numeros.numeros.length, 500); // limita a 500 exibidos
  for (let i = 0; i < max; i++) {
    const n = state.numeros.numeros[i];
    const chip = document.createElement('button');
    chip.className = 'num-chip';
    if (n.status === 'pago') chip.classList.add('sold');
    if (state.selected.has(n.numero)) chip.classList.add('selected');
    chip.textContent = fmtNum(n.numero);
    chip.disabled = n.status === 'pago';
    chip.addEventListener('click', () => toggle(n.numero));
    grid.appendChild(chip);
  }
  if (state.numeros.numeros.length > max) {
    const more = document.createElement('div');
    more.style.gridColumn = '1/-1';
    more.style.textAlign = 'center';
    more.style.fontSize = '12px';
    more.style.color = 'var(--muted)';
    more.style.padding = '8px';
    more.textContent = `+${state.numeros.numeros.length - max} números ocultos (use os pacotes acima)`;
    grid.appendChild(more);
  }
}

function toggle(n) {
  if (state.selected.has(n)) state.selected.delete(n);
  else state.selected.add(n);
  state.qty = state.selected.size || 1;
  document.getElementById('qty').value = state.qty;
  renderNumbers();
  updateTotal();
}

function autoPick(qty) {
  const livre = state.numeros.numeros.filter((n) => n.status === 'disponivel').slice(0, qty);
  state.selected = new Set(livre.map((n) => n.numero));
  state.qty = state.selected.size;
  document.getElementById('qty').value = state.qty;
}

function updateTotal() {
  const qty = state.selected.size || Number(document.getElementById('qty').value || 1);
  const total = state.rifa.preco_por_numero * qty;
  document.getElementById('total-pill').textContent = fmtBRL(total);
}

// ---------- binding ----------
function bind() {
  document.getElementById('btn-minus').onclick = () => adjust(-1);
  document.getElementById('btn-plus').onclick = () => adjust(+1);
  document.getElementById('qty').oninput = (e) => {
    const v = Math.max(1, Number(e.target.value || 1));
    if (v !== state.selected.size) autoPick(v);
    renderNumbers();
    updateTotal();
  };
  document.querySelectorAll('.qty-card').forEach((c) => {
    c.onclick = () => {
      const q = Number(c.dataset.qty);
      autoPick(q);
      document.querySelectorAll('.qty-card').forEach((x) => x.classList.remove('selected'));
      c.classList.add('selected');
      renderNumbers();
      updateTotal();
      // scroll suave pra grade
      document.getElementById('numbers-grid').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
  });
  document.getElementById('btn-buy').onclick = openCheckout;
}

function adjust(delta) {
  const v = Math.max(1, Number(document.getElementById('qty').value || 1) + delta);
  document.getElementById('qty').value = v;
  if (v !== state.selected.size) autoPick(v);
  renderNumbers();
  updateTotal();
}

// ---------- checkout ----------
function openCheckout() {
  if (state.rifa.status !== 'ativa') {
    toast('Essa rifa não está ativa', 'error');
    return;
  }
  const qty = state.selected.size || 1;
  const total = state.rifa.preco_por_numero * qty;
  openSheet(`
    <h3>🎟️ Finalizar compra</h3>
    <p class="sub">${qty} número(s) — <b>${fmtBRL(total)}</b></p>

    <div class="input-group"><label>Nome completo</label><input id="ck-nome" placeholder="Seu nome"/></div>
    <div class="input-group"><label>WhatsApp</label><input id="ck-tel" placeholder="(11) 99999-9999"/></div>
    <div class="input-group"><label>E-mail <span style="opacity:0.5">(opcional)</span></label><input id="ck-email" placeholder="seu@email.com"/></div>

    <button class="btn btn-primary btn-block" id="ck-go" style="margin-top:8px">Gerar Pix →</button>

    <div id="pix-area" style="display:none">
      <div class="pix-display">
        <div class="qr-img"><div id="qr"></div></div>
        <div class="copy-line">
          <input id="pix-code" readonly value=""/>
          <button onclick="copiarPix()">Copiar</button>
        </div>
        <div class="pix-status pending" id="pix-status">
          <span class="dot"></span> <span>Aguardando pagamento…</span>
        </div>
      </div>
      <div style="text-align:center;color:var(--muted);font-size:12px">
        💡 No modo demo, o pagamento é simulado em 6 segundos.
      </div>
    </div>

    <button class="btn btn-ghost btn-block" onclick="closeSheet()" style="margin-top:12px">Cancelar</button>
  `);
  document.getElementById('ck-go').onclick = submitCheckout;
}

async function submitCheckout() {
  const payload = {
    rifa_id: RIFA_ID,
    numeros: [...state.selected].sort((a, b) => a - b),
    comprador_nome: document.getElementById('ck-nome').value.trim(),
    comprador_telefone: document.getElementById('ck-tel').value.trim(),
    comprador_email: document.getElementById('ck-email').value.trim() || null,
  };
  if (!payload.comprador_nome || !payload.comprador_telefone) {
    toast('Preencha nome e WhatsApp', 'error');
    return;
  }
  const btn = document.getElementById('ck-go');
  btn.disabled = true;
  btn.innerHTML = '<span style="display:inline-block;width:14px;height:14px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:spin 0.6s linear infinite"></span> Gerando…';
  try {
    const pedido = await api.comprar(payload);
    showPix(pedido);
    // fica escutando confirmação demo
  } catch (e) {
    toast(e.message, 'error');
    btn.disabled = false;
    btn.innerHTML = 'Gerar Pix →';
  }
}

function showPix(pedido) {
  document.getElementById('pix-area').style.display = 'block';
  document.getElementById('pix-code').value = pedido.pix?.qr_code || '';
  // Gera QR visual a partir do texto (SVG simples com grid)
  const qr = document.getElementById('qr');
  qr.innerHTML = renderQrSvg(pedido.pix?.qr_code || '');
  document.getElementById('ck-go').style.display = 'none';
}

function copiarPix() {
  const v = document.getElementById('pix-code').value;
  navigator.clipboard.writeText(v).then(() => toast('Código Pix copiado!', 'success'));
  // Polling de status (real: consultaria API; demo: atualiza quando evento dispara)
  pollPayment();
}

async function pollPayment() {
  // Real: ficaria consultando /api/pedidos/<id>/status. Aqui só aguardamos evento demo.
}

function onPagamentoDemo(e) {
  if (e.detail.id !== RIFA_ID) return;
  // Atualiza grade
  api.listarNumeros(RIFA_ID).then((nums) => {
    state.numeros = nums;
    updateProgress();
    renderNumbers();
  });
  const status = document.getElementById('pix-status');
  status.classList.remove('pending');
  status.classList.add('ok');
  status.innerHTML = '<span class="dot"></span> <span>✓ Pagamento confirmado! Boa sorte 🍀</span>';
  showConfete();
  setTimeout(() => {
    closeSheet();
    toast('Números comprados com sucesso! 🎉', 'success');
  }, 2500);
}

// ---------- QR SVG fake (parecido com QR code) ----------
function renderQrSvg(text) {
  const size = 21;
  let hash = 0;
  for (const c of text) hash = (hash * 31 + c.charCodeAt(0)) >>> 0;
  let cells = '';
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      // Pseudo-aleatório determinístico
      hash = (hash * 1103515245 + 12345) >>> 0;
      const on = (hash & 0xff) > 110;
      // Cantos com "encontre" (QR-style)
      const corner = (x < 7 && y < 7) || (x >= size - 7 && y < 7) || (x < 7 && y >= size - 7);
      if (corner) continue;
      if (on) cells += `<rect x="${x}" y="${y}" width="1" height="1" fill="#000"/>`;
    }
  }
  // Cantos do QR
  const corners = [
    [0, 0], [size - 7, 0], [0, size - 7],
  ];
  let markers = '';
  for (const [cx, cy] of corners) {
    markers += `<rect x="${cx}" y="${cy}" width="7" height="7" fill="#000"/>`;
    markers += `<rect x="${cx + 1}" y="${cy + 1}" width="5" height="5" fill="#fff"/>`;
    markers += `<rect x="${cx + 2}" y="${cy + 2}" width="3" height="3" fill="#000"/>`;
  }
  return `<svg viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%">
    <rect width="${size}" height="${size}" fill="#fff"/>
    ${cells}${markers}
  </svg>`;
}

// ---------- compartilhamento ----------
function compartilhar(rede) {
  const url = encodeURIComponent(location.href);
  const txt = encodeURIComponent('Tô participando de ' + state.rifa.titulo + ' na RifaVIP! Bora?');
  const urls = {
    facebook: `https://www.facebook.com/sharer/sharer.php?u=${url}`,
    twitter: `https://twitter.com/intent/tweet?url=${url}&text=${txt}`,
    telegram: `https://t.me/share/url?url=${url}&text=${txt}`,
    whatsapp: `https://wa.me/?text=${txt}%20${url}`,
  };
  window.open(urls[rede], '_blank', 'width=600,height=400');
}

// CSS spinner
const css = document.createElement('style');
css.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
document.head.appendChild(css);

load();
showModoBanner();
document.body.classList.add('has-modo-banner');