// ---- Config ----
const PRECO_TITULO = 0.25;
const PACOTES = [
    { qtd: 20,   tag: null,           tagGold: false },
    { qtd: 50,   tag: "Popular",      tagGold: false },
    { qtd: 100,  tag: "Melhor Custo", tagGold: false },
    { qtd: 250,  tag: "Sorte Extra",  tagGold: false },
    { qtd: 500,  tag: "Top Comprador", tagGold: true },
    { qtd: 1000, tag: null,           tagGold: false },
];

let qtdAtual = 100;

const brl = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const $ = (id) => document.getElementById(id);

// ---- Render pacotes ----
function renderPacotes() {
    const wrap = $("packages");
    wrap.innerHTML = PACOTES.map((p) => `
        <div class="pkg ${p.qtd === qtdAtual ? "is-selected" : ""}" data-qtd="${p.qtd}">
            ${p.tag ? `<span class="pkg-tag ${p.tagGold ? "gold" : ""}">${p.tag}</span>` : ""}
            <div class="pkg-qty">+${p.qtd.toLocaleString("pt-BR")}<br><span>números</span></div>
            <div class="pkg-price">${brl(p.qtd * PRECO_TITULO)}</div>
            <div class="pkg-select">${p.qtd === qtdAtual ? "Selecionado ✓" : "Selecionar"}</div>
        </div>
    `).join("");
    wrap.querySelectorAll(".pkg").forEach((el) => {
        el.addEventListener("click", () => setQtd(parseInt(el.dataset.qtd, 10)));
    });
}

function setQtd(q) {
    qtdAtual = Math.max(1, q || 1);
    $("qtyInput").value = qtdAtual;
    renderPacotes();
    updateTotal();
}

function updateTotal() {
    const total = qtdAtual * PRECO_TITULO;
    $("totalValue").textContent = brl(total);
    $("totalQty").textContent = `${qtdAtual.toLocaleString("pt-BR")} números`;
}

// ---- Stepper ----
$("qtyPlus").addEventListener("click", () => setQtd(qtdAtual + 10));
$("qtyMinus").addEventListener("click", () => setQtd(qtdAtual - 10));
$("qtyInput").addEventListener("input", (e) => {
    const v = parseInt(e.target.value, 10);
    qtdAtual = isNaN(v) || v < 1 ? 1 : v;
    renderPacotes();
    updateTotal();
});

// ---- Hero thumbs ----
$("heroThumbs").querySelectorAll(".thumb").forEach((t) => {
    t.addEventListener("click", () => {
        $("heroImg").src = t.dataset.src;
        $("heroThumbs").querySelectorAll(".thumb").forEach((x) => x.classList.remove("is-active"));
        t.classList.add("is-active");
    });
});

// ---- Máscaras ----
function maskCPF(v) {
    return v.replace(/\D/g, "").slice(0, 11)
        .replace(/^(\d{3})(\d)/, "$1.$2")
        .replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3")
        .replace(/\.(\d{3})(\d)/, ".$1-$2");
}
function maskPhone(v) {
    return v.replace(/\D/g, "").slice(0, 11)
        .replace(/^(\d{2})(\d)/, "($1) $2")
        .replace(/(\d{5})(\d)/, "$1-$2");
}
document.querySelector('[name="cpf"]').addEventListener("input", (e) => { e.target.value = maskCPF(e.target.value); });
document.querySelector('[name="telefone"]').addEventListener("input", (e) => { e.target.value = maskPhone(e.target.value); });

// ---- Modal ----
const modal = $("modal");
function openModal() {
    showStep("stepForm");
    $("modalQty").textContent = qtdAtual.toLocaleString("pt-BR");
    $("modalTotal").textContent = brl(qtdAtual * PRECO_TITULO);
    modal.hidden = false;
    document.body.style.overflow = "hidden";
}
function closeModal() {
    modal.hidden = true;
    document.body.style.overflow = "";
    stopPolling();
}
function showStep(id) {
    ["stepForm", "stepPix", "stepSuccess"].forEach((s) => { $(s).hidden = s !== id; });
}
$("participarBtn").addEventListener("click", openModal);
$("modalClose").addEventListener("click", closeModal);
$("successClose").addEventListener("click", closeModal);
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

// ---- Checkout / PIX ----
let pollTimer = null;
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

$("checkoutForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("gerarPixBtn");
    const data = Object.fromEntries(new FormData(e.target).entries());
    btn.disabled = true;
    btn.textContent = "Gerando PIX…";
    try {
        const res = await fetch("/api/pix", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                qtd: qtdAtual,
                nome: data.nome,
                cpf: (data.cpf || "").replace(/\D/g, ""),
                telefone: (data.telefone || "").replace(/\D/g, ""),
                email: data.email || null,
            }),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail || "Erro ao gerar o PIX");

        $("pixQty").textContent = qtdAtual.toLocaleString("pt-BR");
        $("pixTotal").textContent = brl(qtdAtual * PRECO_TITULO);
        $("pixCode").value = json.qr_code || "";
        if (json.qr_code_base64) {
            $("pixQrImg").src = "data:image/png;base64," + json.qr_code_base64;
        }
        showStep("stepPix");
        startPolling(json.payment_id);
    } catch (err) {
        alert("😕 " + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "Gerar PIX 🔒";
    }
});

$("copyPixBtn").addEventListener("click", () => {
    const code = $("pixCode").value;
    navigator.clipboard.writeText(code).then(() => {
        const b = $("copyPixBtn");
        b.textContent = "Copiado ✓";
        setTimeout(() => (b.textContent = "Copiar"), 2000);
    });
});

function startPolling(paymentId) {
    stopPolling();
    pollTimer = setInterval(async () => {
        try {
            const res = await fetch("/api/pix/" + paymentId);
            const json = await res.json();
            if (json.status === "approved" || json.status === "paid") {
                stopPolling();
                $("successQty").textContent = qtdAtual.toLocaleString("pt-BR");
                renderNums($("successNums"), json.numeros || []);
                showStep("stepSuccess");
                loadRanking();
                loadRankingGeral();
                loadStats();
            }
        } catch (_) { /* silencioso */ }
    }, 5000);
}

// ---- Ranking MENOR COTA (topo, ao vivo) ----
async function loadRanking() {
    try {
        const res = await fetch("/api/ranking?periodo=menor");
        const list = await res.json();
        renderRankingMenor(list);
    } catch (_) {
        renderRankingMenor([]);
    }
}
function renderRankingMenor(list) {
    const el = document.getElementById("rankListMenor");
    if (!el) return;
    if (!list.length) {
        el.innerHTML = `<div class="rank-empty">Ainda não há compras registradas nesta janela.</div>`;
        return;
    }
    el.innerHTML = list.map((item, i) => {
        const pos = i + 1;
        const cls = pos === 1 ? "rank-lead" : "";
        return `<li class="${cls}">
            <span class="pos">${pos}º</span>
            <span class="nm">${escapeHtml(item.nome)}</span>
            <span class="qt"><small>cota</small> ${item.cota}</span>
        </li>`;
    }).join("");
}
// ---- Ranking GERAL (maiores compradores, seção separada) ----
async function loadRankingGeral() {
    try {
        const list = await fetch("/api/ranking?periodo=geral").then((r) => r.json());
        renderRankingGeral(list);
    } catch (_) {
        renderRankingGeral([]);
    }
}
function renderRankingGeral(list) {
    const podium = document.getElementById("podiumGeral");
    const rankList = document.getElementById("rankListGeral");
    if (!podium || !rankList) return;
    if (!list.length) {
        podium.innerHTML = "";
        rankList.innerHTML = `<div class="rank-empty">🍀 Seja o primeiro a comprar e liderar!</div>`;
        return;
    }
    const top3 = list.slice(0, 3);
    const order = [top3[1], top3[0], top3[2]]; // 2º, 1º, 3º
    const medals = { 0: "🥇", 1: "🥈", 2: "🥉" };
    const posName = { 0: "1º LUGAR", 1: "2º LUGAR", 2: "3º LUGAR" };
    podium.innerHTML = order.map((item) => {
        if (!item) return `<div></div>`;
        const realIdx = list.indexOf(item);
        return `
        <div class="podium-card ${realIdx === 0 ? "first" : ""}">
            <div class="podium-medal">${medals[realIdx]}</div>
            <div class="podium-pos">${posName[realIdx]}</div>
            <div class="podium-name">${escapeHtml(item.nome)}</div>
            <div class="podium-qty">${item.titulos.toLocaleString("pt-BR")} <small>números</small></div>
        </div>`;
    }).join("");
    rankList.innerHTML = list.slice(3, 10).map((item, i) => `
        <li><span class="pos">${i + 4}º</span><span class="nm">${escapeHtml(item.nome)}</span><span class="qt">${item.titulos.toLocaleString("pt-BR")}</span></li>
    `).join("");
}

// tempo real: atualiza os dois rankings a cada 15s
setInterval(() => { loadRanking(); loadRankingGeral(); }, 15000);
function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- Números helpers ----
function renderNums(container, numeros) {
    if (!numeros || !numeros.length) {
        container.innerHTML = `<span style="color:var(--text-dim)">Números sendo processados…</span>`;
        return;
    }
    container.innerHTML = numeros.map((n) => `<span class="num">${n}</span>`).join("");
}

// ---- Stats (progresso da campanha, com 6% fictício) ----
async function loadStats() {
    try {
        const s = await fetch("/api/stats").then((r) => r.json());
        const pct = Math.min(100, s.pct);
        $("progressPct").textContent = pct.toLocaleString("pt-BR") + "%";
        $("progressFill").style.width = pct + "%";
        $("vendidosTxt").textContent = s.vendidos.toLocaleString("pt-BR") + " números vendidos";
        $("totalNumTxt").textContent = s.total.toLocaleString("pt-BR") + " no total";
    } catch (_) { /* silencioso */ }
}

// ---- Login / Meus números ----
const loginModal = $("loginModal");
function openLogin() {
    $("loginStepForm").hidden = false;
    $("loginStepResult").hidden = true;
    $("loginError").textContent = "";
    $("loginForm").reset();
    loginModal.hidden = false;
    document.body.style.overflow = "hidden";
}
function closeLogin() {
    loginModal.hidden = true;
    document.body.style.overflow = "";
}
$("loginBtn").addEventListener("click", (e) => { e.preventDefault(); openLogin(); });
$("meusNumerosLink").addEventListener("click", (e) => { e.preventDefault(); openLogin(); });
$("loginClose").addEventListener("click", closeLogin);
$("loginBack").addEventListener("click", () => { $("loginStepForm").hidden = false; $("loginStepResult").hidden = true; });
loginModal.addEventListener("click", (e) => { if (e.target === loginModal) closeLogin(); });

// máscaras do modal de login
loginModal.querySelector('[name="cpf"]').addEventListener("input", (e) => { e.target.value = maskCPF(e.target.value); });
loginModal.querySelector('[name="telefone"]').addEventListener("input", (e) => { e.target.value = maskPhone(e.target.value); });

$("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("loginSubmit");
    const data = Object.fromEntries(new FormData(e.target).entries());
    $("loginError").textContent = "";
    btn.disabled = true; btn.textContent = "Consultando…";
    try {
        const res = await fetch("/api/meus-numeros", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                cpf: (data.cpf || "").replace(/\D/g, ""),
                telefone: (data.telefone || "").replace(/\D/g, ""),
            }),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail || "Não foi possível consultar.");
        if (!json.total) {
            $("loginError").textContent = "Encontramos seu cadastro, mas ainda não há pagamento confirmado.";
            return;
        }
        $("resNome").textContent = (json.nome || "participante").split(" ")[0];
        $("resTotal").textContent = json.total.toLocaleString("pt-BR");
        renderNums($("resNums"), json.numeros);
        $("resPedidos").innerHTML = json.pedidos.map((p) => {
            const d = p.data ? new Date(p.data).toLocaleDateString("pt-BR") : "—";
            return `<div class="res-pedido"><strong>${p.qtd} números</strong> · ${brl(p.valor)} · ${d}</div>`;
        }).join("");
        $("loginStepForm").hidden = true;
        $("loginStepResult").hidden = false;
    } catch (err) {
        $("loginError").textContent = "😕 " + err.message;
    } finally {
        btn.disabled = false; btn.textContent = "Ver meus números";
    }
});

// ---- Init ----
$("year").textContent = new Date().getFullYear();
renderPacotes();
updateTotal();
loadRanking();
loadRankingGeral();
loadStats();
