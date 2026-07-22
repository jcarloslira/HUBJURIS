# Deploy do LexHub no Render (para o Dr. Wilker acessar)

Guia passo a passo para publicar o LexHub numa URL fixa na internet.
Tempo estimado: ~15 minutos.

---

## Antes de começar — segurança

- ✅ O `.env` (com suas chaves) **nunca** vai para o Git — já está no `.gitignore`.
  No Render, você cola as chaves direto no painel (elas ficam só lá).
- ⚠️ **Use um repositório PRIVADO** para o LexHub. O repo atual (`sitenaeliton`) é
  **público** e contém a `proposta.html` confidencial do Dr. Wilker. Não publique
  o LexHub num repo público.

---

## Passo 1 — Código num repositório privado no GitHub

1. No GitHub, crie um **repositório privado** novo (ex.: `lexhub`). Não marque
   "Add a README".
2. No terminal, dentro de `C:\Users\jc208\Downloads\claude`, aponte para ele e
   suba **apenas o que o deploy precisa** (evita mandar prints e arquivos soltos):

   ```bash
   git remote add lexhub https://github.com/SEU_USUARIO/lexhub.git
   git add app/ sql/ Dockerfile pyproject.toml uv.lock .env.example .gitignore CLAUDE.md DEPLOY.md
   git commit -m "feat: LexHub pronto para deploy no Render"
   git push lexhub feat/hub-condominial-ia:main
   ```

   > Isso envia a branch atual para o `main` do repo novo, sem os prints/JSONs
   > soltos na raiz. (Se preferir, posso fazer esse commit/push por você.)

---

## Passo 2 — Criar o Web Service no Render

1. Acesse **https://dashboard.render.com** → **New +** → **Web Service**.
2. Conecte sua conta do GitHub e selecione o repositório `lexhub`.
3. O Render detecta o **Dockerfile** automaticamente. Confira:
   - **Language / Runtime:** Docker
   - **Branch:** `main`
   - **Instance Type:** Free (dá para começar; veja os avisos no fim)
4. **NÃO** clique em "Create" ainda — primeiro configure as variáveis (Passo 3).

---

## Passo 3 — Variáveis de ambiente (as chaves)

Em **Environment** → **Add Environment Variable**, adicione uma a uma
(os valores estão no seu `.env` local):

| Chave | Valor |
|---|---|
| `HUB_PUBLICO` | `true`  ← **essencial**, é o que libera o hub para o Dr. Wilker |
| `APP_ENV` | `production` |
| `SUPABASE_URL` | (do seu `.env`) |
| `SUPABASE_ANON_KEY` | (do seu `.env`) |
| `SUPABASE_SERVICE_ROLE_KEY` | (do seu `.env`) |
| `ANTHROPIC_API_KEY` | (do seu `.env`) |
| `SECRET_KEY` | (do seu `.env`, ou qualquer texto aleatório) |

Opcionais (só quando ativar o Google Drive dos escritórios):
`COMPOSIO_API_KEY`, `COMPOSIO_GDRIVE_AUTH_CONFIG_ID`, `COMPOSIO_BASE_URL`.

> **Sem `HUB_PUBLICO=true`, o Dr. Wilker verá "404"** — o hub fica bloqueado para
> fora por padrão (proteção contra uso indevido de tokens).

---

## Passo 4 — Publicar

1. Clique em **Create Web Service**. O Render vai buildar a imagem Docker
   (~3–5 min na primeira vez).
2. Quando aparecer **"Live"**, sua URL estará no topo, algo como
   **`https://lexhub.onrender.com`**.
3. Abra a URL — deve cair na tela de **login/cadastro** do LexHub. 🎉

---

## Passo 5 — Enviar ao Dr. Wilker

Mande a URL para ele. No primeiro acesso ele vai:
1. Clicar em **"Criar conta"**;
2. Preencher nome, nome do escritório, e-mail e senha;
3. Entrar direto no hub — já como **admin** do escritório dele.

O banco (Supabase) já está na nuvem, então a conta dele é criada na hora, sem
nenhum setup adicional da sua parte.

---

## Avisos para o demo não te surpreender

- **Render Free "dorme"** após ~15 min sem uso: o **primeiro acesso** depois disso
  demora ~40s para "acordar". Se quiser evitar na frente do cliente, abra a URL
  alguns minutos antes, ou suba para o plano pago (~US$7/mês, sem sleep).
- **Supabase Free pausa** após ~7 dias de inatividade. Se acontecer, o cadastro
  falha com "sem conexão" — é só me avisar que eu reativo (ou use com frequência).
- **Consumo de tokens:** a URL é privada e o hub exige login, mas o endpoint de
  chat ainda funciona sem token (degradado). Como o link é só para o Dr. Wilker,
  está ok para o demo. Quando virar produto para vários assinantes, a gente tranca
  o chat para exigir login sempre (me peça e eu faço).

---

## Atualizar depois de mudanças

Toda vez que você (ou eu) mudar o código:

```bash
git add app/ sql/ Dockerfile pyproject.toml uv.lock
git commit -m "descrição da mudança"
git push lexhub feat/hub-condominial-ia:main
```

O Render **redeploya sozinho** a cada push no `main`. 🔁
