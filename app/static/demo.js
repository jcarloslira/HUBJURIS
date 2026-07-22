/* =============================================================
   RIFA VIP — Modo Demo
   Quando não há Supabase configurado, este módulo mantém uma
   rifa de exemplo no localStorage pra tudo ser navegável.
   ============================================================= */

const DEMO_FLAG = 'rifavip_demo_v3';
const DEMO_BUILD = '2026.07.10-jbl-final';

// Limpa caches de versões antigas (forçar refresh ao subir versão)
['rifavip_demo', 'rifavip_demo_v2'].forEach((old) => localStorage.removeItem(old));

// Cria dados iniciais no localStorage na primeira vez
(function seed() {
  if (localStorage.getItem(DEMO_FLAG)) return;
  const rifas = [
    {
      id: 'demo-1',
      titulo: 'JBL Boombox 4',
      subtitulo: 'PARTICIPE E CONCORRA!',
      descricao:
        '🔊 JBL Boombox 4 — Som massivo o dia todo.\n\n' +
        'Caixa de som portátil Bluetooth na cor preta, lacrada, com a qualidade lendária da JBL. ' +
        'Equipada com alça de transporte integrada, bateria de longa duração, resistência à água e poeira e ' +
        'o grave potente que é marca registrada da linha Boombox.\n\n' +
        '📦 O que está incluso:\n' +
        '• 1× Caixa JBL Boombox 4 (lacrada, com nota fiscal)\n' +
        '• Cabo de carregamento\n' +
        '• Embalagem original\n\n' +
        '🎲 Como funciona o sorteio:\n' +
        '• Escolha quantos números quer comprar (cada número dá uma chance)\n' +
        '• Pague via Pix e pronto — seus números ficam reservados em seu nome\n' +
        '• No dia do sorteio, divulgamos o ganhador ao vivo com transmissão aberta\n' +
        '• Entregamos o prêmio em todo o Brasil, sem custo para o ganhador\n\n' +
        'Boa sorte! 🍀',
      imagem_url: '/static/fotos/jbl-boombox.svg',
      imagem_emoji: '🔊',
      preco_por_numero: 0.50,
      total_numeros: 1000,
      data_sorteio: new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString(),
      status: 'ativa',
      numeros_vendidos: 0,
    },
    {
      id: 'hilux-diesel-2024',
      slug: 'hilux-diesel-2024',
      titulo: 'Toyota Hilux Diesel 2024',
      subtitulo: '0KM — Sorteio online',
      descricao: '(Descrição a ser preenchida pelo administrador)',
      imagem_url: null,
      imagem_emoji: '🚙',
      preco_por_numero: 9.99,
      total_numeros: 50000,
      data_sorteio: new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString(),
      status: 'ativa',
      numeros_vendidos: 0,
    },
  ];
  const numeros = {
    'demo-1': Array.from({ length: 1000 }, (_, i) => ({ numero: i, status: 'disponivel' })),
    'hilux-diesel-2024': Array.from({ length: 50000 }, (_, i) => ({ numero: i, status: 'disponivel' })),
  };
  localStorage.setItem(DEMO_FLAG, JSON.stringify({ rifas, numeros }));
})();

// ---------- API demo ----------
const demo = {
  get rifas() { return JSON.parse(localStorage.getItem(DEMO_FLAG)).rifas; },
  set rifas(v) {
    const data = JSON.parse(localStorage.getItem(DEMO_FLAG));
    data.rifas = v;
    localStorage.setItem(DEMO_FLAG, JSON.stringify(data));
  },
  get numeros() { return JSON.parse(localStorage.getItem(DEMO_FLAG)).numeros; },
  set numeros(v) {
    const data = JSON.parse(localStorage.getItem(DEMO_FLAG));
    data.numeros = v;
    localStorage.setItem(DEMO_FLAG, JSON.stringify(data));
  },

  // Listar rifas (ativas, encerradas e sorteadas)
  listarRifas() {
    return Promise.resolve(this.rifas);
  },
  // Detalhes de uma rifa (aceita id ou slug)
  obterRifa(id) {
    const r = this.rifas.find((x) => x.id === id || x.slug === id);
    if (!r) return Promise.reject(new Error('Rifa não encontrada'));
    return Promise.resolve(r);
  },
  // Números de uma rifa (aceita id ou slug)
  listarNumeros(id) {
    const r = this.rifas.find((x) => x.id === id || x.slug === id);
    const realId = r ? r.id : id;
    const nums = this.numeros[realId] || [];
    const total = r?.total_numeros || nums.length;
    return Promise.resolve({
      rifa_id: id, total,
      disponiveis: nums.filter((n) => n.status === 'disponivel').length,
      reservados: nums.filter((n) => n.status === 'reservado').length,
      pagos: nums.filter((n) => n.status === 'pago').length,
      numeros: nums,
    });
  },
  // Comprar números (aceita id ou slug)
  comprar(id, numeros, comprador) {
    const r = this.rifas.find((x) => x.id === id || x.slug === id);
    const realId = r ? r.id : id;
    const ns = this.numeros[realId];
    for (const n of numeros) {
      if (ns[n].status !== 'disponivel') return Promise.reject(new Error(`Número ${n} indisponível`));
      ns[n].status = 'reservado';
    }
    this.numeros = { ...this.numeros, [realId]: ns };
    const pedidoId = 'pedido-' + Date.now();
    // Simula confirmação automática de pagamento após 6 segundos
    setTimeout(() => {
      const cur = this.numeros[realId];
      numeros.forEach((n) => { cur[n].status = 'pago'; });
      // Atualiza rifa com vendas
      const rifa = this.rifas.find((x) => x.id === realId);
      rifa.numeros_vendidos += numeros.length;
      this.rifas = [...this.rifas];
      this.numeros = { ...this.numeros };
      toast('Pagamento confirmado! 🎉', 'success');
      // Avisa listeners
      window.dispatchEvent(new CustomEvent('demo:pagamento', { detail: { id: realId, numeros } }));
    }, 6000);
    return Promise.resolve({
      pedido_id: pedidoId,
      rifa_id: realId,
      numeros,
      valor_total: r.preco_por_numero * numeros.length,
      status: 'pendente',
      pix: {
        payment_id: 'mp-demo-' + Date.now(),
        qr_code: '00020126580014BR.GOV.BCB.PIX0136demo-pix-key@example.com520400005303986540' +
                 (r.preco_por_numero * numeros.length).toFixed(2) +
                 '5802BR6009SAO PAULO62070503***6304ABCD',
        qr_code_base64: null,
        ticket_url: null,
        valor_total: r.preco_por_numero * numeros.length,
        expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
      },
    });
  },
  // Admin: criar rifa
  criarRifa(payload) {
    const id = 'rifa-' + Date.now();
    const nova = {
      id,
      ...payload,
      status: 'ativa',
      numeros_vendidos: 0,
    };
    const nums = [];
    for (let i = 0; i < payload.total_numeros; i++) {
      nums.push({ numero: i, status: 'disponivel' });
    }
    this.numeros = { ...this.numeros, [id]: nums };
    this.rifas = [...this.rifas, nova];
    return Promise.resolve(nova);
  },
  // Admin: atualizar rifa
  atualizarRifa(id, payload) {
    const i = this.rifas.findIndex((x) => x.id === id);
    if (i < 0) return Promise.reject(new Error('Rifa não encontrada'));
    this.rifas = this.rifas.map((r, idx) => idx === i ? { ...r, ...payload } : r);
    return Promise.resolve(this.rifas[i]);
  },
  // Admin: sortear
  sortear(id) {
    const nums = this.numeros[id].filter((n) => n.status === 'pago');
    if (!nums.length) return Promise.reject(new Error('Sem números pagos'));
    const sorteado = nums[Math.floor(Math.random() * nums.length)];
    this.rifas = this.rifas.map((r) => r.id === id ? {
      ...r,
      status: 'sorteada',
      numero_sorteado: sorteado.numero,
      ganhador_nome: sorteado.comprador_nome || 'Anônimo',
    } : r);
    return Promise.resolve({ rifa_id: id, numero_sorteado: sorteado.numero });
  },
  // Resetar demo
  resetar() {
    localStorage.removeItem(DEMO_FLAG);
    location.reload();
  },
};

// ---------- API real com fallback demo ----------
// Estratégia:
// 1. Tenta o backend real (Supabase + FastAPI).
// 2. Se 503 (sem Supabase configurado), cai no demo local.
// 3. O usuário SEMPRE vê um banner claro dizendo qual modo está rodando.
const api = {
  modo: 'carregando',
  async _try(url, opts = {}, fallback) {
    try {
      const r = await fetch(url, opts);
      if (r.status === 503 || r.status === 404) {
        // Backend existe mas sem dados configurados → entra em demo
        api.modo = 'demo';
        return await fallback();
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      api.modo = 'producao';
      return await r.json();
    } catch (e) {
      api.modo = 'demo';
      return await fallback();
    }
  },
  async listarRifas() {
    return this._try('/api/rifas', {}, () => demo.listarRifas());
  },
  async obterRifa(id) {
    return this._try('/api/rifas/' + id, {}, () => demo.obterRifa(id));
  },
  async listarNumeros(id) {
    return this._try('/api/rifas/' + id + '/numeros', {}, () => demo.listarNumeros(id));
  },
  async comprar(payload) {
    return this._try('/api/rifas/comprar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }, () => demo.comprar(payload.rifa_id, payload.numeros, {
      nome: payload.comprador_nome,
      telefone: payload.comprador_telefone,
    }));
  },
  async criarRifaAdmin(payload, token) {
    return this._try('/api/rifas/admin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
      body: JSON.stringify(payload),
    }, () => demo.criarRifa(payload));
  },
  async atualizarRifaAdmin(id, payload, token) {
    return this._try('/api/rifas/admin/' + id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
      body: JSON.stringify(payload),
    }, () => demo.atualizarRifa(id, payload));
  },
  async sortearAdmin(id, token) {
    return this._try('/api/rifas/admin/sortear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
      body: JSON.stringify({ rifa_id: id }),
    }, () => demo.sortear(id));
  },
};

// Detecta modo de execução e mostra banner global
function showModoBanner() {
  if (api.modo !== 'demo') return;
  if (document.querySelector('.modo-banner')) return;
  const banner = document.createElement('div');
  banner.className = 'modo-banner';
  banner.innerHTML = `
    <span><b>⚠️ Modo demonstração</b> — sem Supabase configurado, dados são locais do seu navegador.
    Configure <code>SUPABASE_URL</code> e <code>MERCADO_PAGO_ACCESS_TOKEN</code> no <code>.env</code> pra produção.</span>
    <button onclick="this.parentElement.remove()">×</button>`;
  document.body.prepend(banner);
}

// ---------- Helpers de UI ----------
function fmtBRL(v) { return 'R$ ' + Number(v).toFixed(2).replace('.', ','); }
function fmtDate(iso) {
  return new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
}
function fmtNum(n) { return String(n).padStart(3, '0'); }
function escapeHTML(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
function countdown(iso) {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return 'Encerrado';
  const d = Math.floor(ms / (1000 * 60 * 60 * 24));
  const h = Math.floor((ms % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
  if (d > 0) return `${d}d ${h}h`;
  return `${h}h ${Math.floor((ms % 3.6e6) / 60000)}m`;
}

function toast(msg, kind = '') {
  let stack = document.querySelector('.toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.className = 'toast-stack';
    document.body.appendChild(stack);
  }
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  stack.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity 0.4s, transform 0.4s';
    el.style.opacity = '0';
    el.style.transform = 'translateX(40px)';
    setTimeout(() => el.remove(), 400);
  }, 4000);
}

function showConfete() {
  const cores = ['#ec4899', '#a855f7', '#fbbf24', '#22c55e', '#26a5e4', '#f97316'];
  const box = document.createElement('div');
  box.className = 'confetti';
  for (let i = 0; i < 80; i++) {
    const s = document.createElement('span');
    s.style.left = (Math.random() * 100) + 'vw';
    s.style.background = cores[Math.floor(Math.random() * cores.length)];
    s.style.animationDelay = (Math.random() * 0.4) + 's';
    s.style.animationDuration = (2 + Math.random() * 2) + 's';
    box.appendChild(s);
  }
  document.body.appendChild(box);
  setTimeout(() => box.remove(), 4500);
}

function openSheet(html) {
  const back = document.createElement('div');
  back.className = 'sheet-backdrop open';
  back.innerHTML = `<div class="sheet">${html}</div>`;
  back.addEventListener('click', (e) => {
    if (e.target === back) closeSheet();
  });
  document.body.appendChild(back);
  return back;
}
function closeSheet() {
  document.querySelectorAll('.sheet-backdrop.open').forEach((el) => el.remove());
}
window.closeSheet = closeSheet;

function revealOnScroll() {
  const els = document.querySelectorAll('.reveal');
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add('in');
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.1 });
  els.forEach((el) => io.observe(el));
}
document.addEventListener('DOMContentLoaded', () => {
  revealOnScroll();
  // Cookies banner
  if (!localStorage.getItem('rifavip_cookies')) {
    setTimeout(() => {
      const el = document.createElement('div');
      el.className = 'cookies';
      el.innerHTML = `
        <div>🍪 Usamos cookies para uma experiência melhor.</div>
        <div class="actions">
          <button class="refuse">Recusar</button>
          <button class="accept">Aceitar</button>
        </div>`;
      el.querySelector('.accept').onclick = () => {
        localStorage.setItem('rifavip_cookies', '1');
        el.classList.add('hide');
      };
      el.querySelector('.refuse').onclick = () => el.classList.add('hide');
      document.body.appendChild(el);
    }, 800);
  }
});

window.api = api;
window.demo = demo;
window.toast = toast;
window.showConfete = showConfete;
window.openSheet = openSheet;
window.fmtBRL = fmtBRL;
window.fmtDate = fmtDate;
window.fmtNum = fmtNum;
window.escapeHTML = escapeHTML;
window.countdown = countdown;