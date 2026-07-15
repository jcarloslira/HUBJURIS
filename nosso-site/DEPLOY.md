# Deploy da Rifa Naeliton Prêmios (Render)

Publica o site num link público `https://...onrender.com`, sempre no ar, com os
dados (pedidos e números) guardados em disco persistente.

## Antes de publicar (segurança — importante)

1. **Gere um Access Token novo** no Mercado Pago (o atual foi exposto no chat).
   Painel MP → Suas integrações → Credenciais de produção.
2. **Escolha um `ADMIN_TOKEN` forte** (não use o padrão `naeliton-painel-2026`).
3. Nunca commite o arquivo `.env` (já está no `.gitignore`).

## Passo a passo

1. **Suba o código para um repositório no GitHub** (pode ser só a pasta `nosso-site/`,
   ou o repositório inteiro com a "Root Directory" apontando para `nosso-site`).

2. Acesse <https://render.com> → **New** → **Blueprint** (ele lê o `render.yaml`),
   ou **New** → **Web Service** e escolha **Docker**.
   - Root Directory: `nosso-site` (se subiu o repo inteiro)
   - Plano: **Starter** (sempre no ar). O Free **dorme e apaga o disco** — não use.

3. Em **Environment**, defina as variáveis (o `render.yaml` já as lista como `sync:false`):
   - `MERCADO_PAGO_ACCESS_TOKEN` = seu token novo de produção
   - `ADMIN_TOKEN` = seu token forte do painel
   - `DB_PATH` = `/data/pedidos.db` (já vem no blueprint)

4. Confirme o **Disk** montado em `/data` (1 GB basta) — é o que preserva os dados.

5. **Deploy**. Ao terminar você recebe a URL pública, ex.:
   - Site: `https://naeliton-premios.onrender.com`
   - Admin: `https://naeliton-premios.onrender.com/admin`

## Depois de publicado — webhook do Mercado Pago (confirmação automática)

Hoje o pagamento é confirmado quando o navegador do cliente consulta o status.
Para confirmar 100% no servidor (mesmo se o cliente fechar a página), configure o
webhook no painel do MP apontando para a sua URL pública. *(Posso adicionar o
endpoint `/api/webhook` quando você quiser.)*

## Rodar localmente

```bash
uv run python nosso-site/server.py      # http://localhost:4600
```

## Upgrade opcional para Postgres

O SQLite em disco já é durável para esta rifa. Se um dia quiser Postgres
(vários servidores, backups gerenciados), me avise que eu adapto a camada de
banco — o resto do código não muda.
