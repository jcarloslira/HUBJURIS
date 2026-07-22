/* ========== Site de Rifas — JS do front ========== */

const fmtBRL = (v) => `R$ ${Number(v).toFixed(2).replace('.', ',')}`;
const fmtDate = (iso) => {
  const d = new Date(iso);
  return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
};

const params = new URLSearchParams(window.location.search);
const RIFA_ID = params.get('id');

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Erro ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

const state = {
  rifa: null,
  numeros: null,
  selected: new Set(),
  qty: 1,
};

// ── Render ─────────────────────────────────────────────────

function render() {
  const r = state.rifa;
  if (!r) return;
  document.title = `${r.titulo} — Sorteio`;

  const hero = document.querySelector('.hero-img');
  if (r.imagem_url) hero.style.setProperty('--hero-img', `url("${r.imagem_url}")`);
  document.querySelector('.hero-info h1').textContent = r.titulo;
  document.querySelector('.hero-info .subtitle').textContent =
    r.subtitulo || 'PARTICIPE E CONCORRA!';

  document.querySelector('[data-bind="data-sorteio"]').textContent = fmtDate(r.data_sorteio);
  document.querySelector('[data-bind="preco"]').textContent = fmtBRL(r.preco_por_numero);
  document.querySelector('[data-bind="descricao"]').innerHTML =
    `<pre class="body">${escapeHTML(r.descricao || 'Sorteio regulado pela legislação vigente.')} </pre>`;

  renderNumbers();
  updateTotal();
}

function renderNumbers() {
  const grid = document.querySelector('.numbers-grid');
  if (!state.numeros) return;
  grid.innerHTML = '';
  state.numeros.numeros.forEach((n) => {
    const chip = document.createElement('button');
    chip.className = 'num-chip';
    chip.textContent = String(n.numero).padStart(3, '0');
    if (n.status === 'pago') chip.classList.add('sold');
    if (state.selected.has(n.numero)) chip.classList.add('selected');
    chip.disabled = n.status === 'pago';
    chip.addEventListener('click', () => toggle(n.numero));
    grid.appendChild(chip);
  });
}

function updateTotal() {
  const qty = state.selected.size || Number(document.querySelector('input.qty').value || 0);
  const total = state.rifa.preco_por_numero * qty;
  document.querySelector('.btn-comprar .price').textContent = fmtBRL(total);
  document.querySelector('input.qty').value = qty;
}

function toggle(n) {
  if (state.selected.has(n)) state.selected.delete(n);
  else state.selected.add(n);
  // Sincroniza com campo de quantidade
  document.querySelector('input.qty').value = state.selected.size;
  renderNumbers();
  updateTotal();
}

// ── Eventos ─────────────────────────────────────────────────

function bindEvents() {
  document.querySelector('.step.minus').onclick = () => {
    const v = Math.max(0, Number(document.querySelector('input.qty').value || 0) - 1);
    document.querySelector('input.qty').value = v;
    state.selected.clear();
    if (v > 0) autoPick(v);
    updateTotal();
    renderNumbers();
  };
  document.querySelector('input.qty').oninput = (e) => {
    const v = Math.max(0, Number(e.target.value || 0));
    state.selected.clear();
    if (v > 0) autoPick(v);
    updateTotal();
    renderNumbers();
  };
  document.querySelector('.btn-comprar').onclick = openCheckout;
  document.querySelector('.modal-close').onclick = closeCheckout;
  document.querySelector('.refuse').onclick = () => document.querySelector('.cookies').classList.add('hide');
  document.querySelector('.cookies button:not(.refuse)').onclick = () => document.querySelector('.cookies').classList.add('hide');
}

function autoPick(qty) {
  // Pega os primeiros disponíveis na grade
  const livre = state.numeros.numeros.filter((n) => n.status !== 'pago').slice(0, qty);
  livre.forEach((n) => state.selected.add(n.numero));
}

async function loadAll() {
  if (!RIFA_ID) {
    document.querySelector('.container').innerHTML =
      '<div class="empty">Passe um <code>?id=&lt;rifa_id&gt;</code> na URL para abrir uma rifa. '
      + 'Ou liste rifas em <a href="/rifas/admin/painel">/rifas/admin/painel</a>.</div>';
    return;
  }
  try {
    const [rifa, numeros] = await Promise.all([
      fetchJSON(`/api/rifas/${RIFA_ID}`),
      fetchJSON(`/api/rifas/${RIFA_ID}/numeros`),
    ]);
    state.rifa = rifa;
    state.numeros = numeros;
    bindEvents();
    render();
  } catch (err) {
    document.querySelector('.container').innerHTML =
      `<div class="empty">Não foi possível carregar: ${err.message}</div>`;
  }
}

// ── Checkout ───────────────────────────────────────────────

function openCheckout() {
  if (state.selected.size === 0) {
    alert('Selecione ao menos um número');
    return;
  }
  document.getElementById('nome').value = '';
  document.getElementById('telefone').value = '';
  document.getElementById('email').value = '';
  document.querySelector('.pix-area').style.display = 'none';
  document.querySelector('.modal-backdrop').classList.add('open');
}

function closeCheckout() {
  document.querySelector('.modal-backdrop').classList.remove('open');
}

async function submitCheckout() {
  const payload = {
    rifa_id: RIFA_ID,
    numeros: [...state.selected].sort((a, b) => a - b),
    comprador_nome: document.getElementById('nome').value.trim(),
    comprador_telefone: document.getElementById('telefone').value.trim(),
    comprador_email: document.getElementById('email').value.trim() || null,
  };
  if (!payload.comprador_nome || !payload.comprador_telefone) {
    alert('Preencha nome e telefone');
    return;
  }
  const btn = document.querySelector('.btn-confirm');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Gerando Pix...';
  try {
    const pedido = await fetchJSON('/api/rifas/comprar', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    showPix(pedido);
    pollPayment(pedido);
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Gerar Pix';
  }
}

function showPix(pedido) {
  document.querySelector('.pix-area').style.display = 'block';
  if (pedido.pix && pedido.pix.qr_code_base64) {
    document.querySelector('img.qr').src = `data:image/png;base64,${pedido.pix.qr_code_base64}`;
  } else {
    document.querySelector('img.qr').style.display = 'none';
  }
  document.getElementById('pix-copia-cola').value = pedido.pix?.qr_code || '';
  document.querySelector('.status').textContent =
    'Aguardando pagamento... escaneie o QR ou copie o código.';
  document.querySelector('.status').classList.remove('ok');
}

async function pollPayment(pedido) {
  const started = Date.now();
  const tick = async () => {
    if (Date.now() - started > 1000 * 60 * 10) return;
    // Como ainda não temos endpoint de consulta por pedido público,
    // recarregamos a grade de números: o servidor muda o status em "pago"
    // automaticamente via webhook do Mercado Pago.
    const numeros = await fetchJSON(`/api/rifas/${RIFA_ID}/numeros`);
    state.numeros = numeros;
    renderNumbers();
    const allPaid = [...state.selected].every((n) =>
      numeros.numeros.find((x) => x.numero === n)?.status === 'pago',
    );
    if (allPaid) {
      document.querySelector('.status').textContent = '✓ Pagamento confirmado! Boa sorte 🍀';
      document.querySelector('.status').classList.add('ok');
      return;
    }
    setTimeout(tick, 4000);
  };
  setTimeout(tick, 4000);
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ── Boot ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.querySelector('#btn-confirm').addEventListener('click', submitCheckout);
  document.querySelector('#copiar-pix').addEventListener('click', () => {
    const v = document.getElementById('pix-copia-cola').value;
    navigator.clipboard.writeText(v).then(() => {
      const b = document.querySelector('#copiar-pix');
      b.textContent = 'Copiado!';
      setTimeout(() => (b.textContent = 'Copiar'), 1500);
    });
  });
  loadAll();
});
