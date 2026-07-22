# Conectores Composio do LexHub

Os conectores usam o **OAuth gerenciado pelo Composio** (`is_composio_managed: true`).
Ou seja: **não há nada de Google Cloud/OAuth para configurar.** Cada escritório
apenas **faz login com a conta Google dele** na tela de Conectores, e pronto —
exatamente como o Google Drive.

## Auth configs já criados (managed OAuth)

Criados via API do Composio; já estão no `.env` (e devem ir para as variáveis do Render):

| Conector | Toolkit | Auth config (`ac_...`) | Variável |
|---|---|---|---|
| Google Drive | `googledrive` | `ac_TRp0RgeWQDT7` | `COMPOSIO_GDRIVE_AUTH_CONFIG_ID` |
| Google Agenda | `googlecalendar` | `ac_ymTG6ppAF2jO` | `COMPOSIO_GCALENDAR_AUTH_CONFIG_ID` |
| Gmail | `gmail` | `ac_y_nQOqK9EiLf` | `COMPOSIO_GMAIL_AUTH_CONFIG_ID` |
| Google Docs | `googledocs` | `ac_wy_UtPRCi_20` | `COMPOSIO_GDOCS_AUTH_CONFIG_ID` |
| Google Sheets | `googlesheets` | `ac_NmTNk7g2v62j` | `COMPOSIO_GSHEETS_AUTH_CONFIG_ID` |
| Google Meet | `googlemeet` | `ac_2fDqfAZi8BZG` | `COMPOSIO_GMEET_AUTH_CONFIG_ID` |

> Os `ac_...` **não são segredo** (são só identificadores). A `COMPOSIO_API_KEY`
> sim — essa fica só no `.env`/variáveis do Render.

## Como o escritório conecta (experiência do usuário)

Em **Configurações → Conectores**, cada serviço tem um botão **"Vincular"**. O
usuário clica, faz login na conta Google do escritório, e o conector fica ativo.
A identidade no Composio é o `escritorio_id` — cada escritório conecta o seu.

## Ações dos agentes (com confirmação)

Uma vez conectado, os agentes ganham ferramentas — **sempre propor-e-confirmar**
antes de qualquer ação externa:
- **Agenda:** criar/consultar eventos (prazos, audiências, assembleias)
- **Gmail:** rascunhar e enviar comunicados a condôminos/síndicos
- **Docs:** gerar a peça/notificação/parecer já como documento no Drive
- **Sheets:** planilhas de inadimplência/cotas
- **Meet:** link de reunião junto com o evento do Agenda

## Adicionar um conector novo no futuro

É só criar um auth config gerenciado para o toolkit desejado (via API do Composio,
`POST /api/v3/auth_configs` com `{"toolkit":{"slug":"..."},"auth_config":{"type":"use_composio_managed_auth"}}`)
e apontar a variável de ambiente correspondente. Nada de Google Cloud.

## Escala (quando abrir para muitos assinantes)

O OAuth gerenciado do Composio usa o app OAuth do próprio Composio — ótimo para o
MVP e o demo. Ao escalar, dá para trocar por credenciais OAuth próprias (verificadas
pelo Google) sem mudar o código do LexHub — só o auth config no Composio.
