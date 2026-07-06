# Monitoramento Diário DOU — MDIC / Inmetro

Automação que roda todo dia às 8h (Brasília) via GitHub Actions: consulta o
Diário Oficial da União (Seção 2) via **INLABS**, filtra publicações **do
MDIC e do Inmetro** (pelo órgão publicador, não por menções no texto), gera
um relatório em Word, publica uma página no GitHub Pages e (opcionalmente)
avisa a equipe no Teams.

---

## 1. Como funciona

```
GitHub Actions (todo dia, 8h de Brasília, ou manual via "Run workflow")
        │
        ▼
src/main.py
        │
        ├─► src/dou_client.py       → baixa o XML do dia no INLABS e filtra por órgão (MDIC/Inmetro)
        ├─► src/report_generator.py → gera relatorio_dou_mdic_AAAA-MM-DD.docx
        ├─► src/html_generator.py   → gera docs/index.html (publicado no GitHub Pages)
        └─► src/teams_notifier.py   → posta resumo no Teams (se configurado)
             (ou src/email_notifier.py, alternativa por e-mail)
```

O `.docx` é commitado em `reports/` (histórico) e a página pública fica em
`https://SEU-USUARIO.github.io/SEU-REPO/`.

**Fonte de dados:** INLABS (`inlabs.in.gov.br`), serviço oficial e gratuito
da Imprensa Nacional — a leitura direta da página pública
(`in.gov.br/leiturajornal`) não funciona em servidores automatizados por
causa do bot manager (Cloudflare) da Imprensa Nacional.

**Filtro:** aplicado sobre o **órgão publicador** de cada ato (equivalente
aos parâmetros `org`/`org_sub` do [link de busca oficial](https://www.in.gov.br/leiturajornal?secao=do2)),
configurável em `DOU_KEYWORDS`. Isso evita trazer publicações de outros
ministérios que apenas *citam* o MDIC/Inmetro no corpo do texto (ex.:
cessão de servidor).

---

## 2. Estrutura do repositório

```
dou-monitor-mdic/
├── .github/workflows/monitor-dou.yml
├── src/
│   ├── config.py             ← configurações (via variáveis de ambiente)
│   ├── dou_client.py         ← busca no INLABS e filtra por órgão
│   ├── report_generator.py   ← gera o .docx
│   ├── html_generator.py     ← gera a página do GitHub Pages
│   ├── teams_notifier.py     ← envia para o Teams (opcional)
│   ├── email_notifier.py     ← envia por e-mail (alternativa)
│   └── main.py                ← orquestra tudo
├── reports/                   ← histórico de .docx gerados
├── docs/                      ← página pública (GitHub Pages)
└── requirements.txt
```

---

## 3. Configurar os GitHub Secrets

**Settings → Secrets and variables → Actions → New repository secret.**

| Secret | Obrigatório | Descrição |
|---|:---:|---|
| `INLABS_EMAIL` | Sim | Login cadastrado em inlabs.in.gov.br |
| `INLABS_SENHA` | Sim | Senha do INLABS |
| `TEAMS_WEBHOOK_URL` | Se usar Teams | URL do Workflow do Teams (ver seção 5) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` | Se usar e-mail | Credenciais SMTP institucionais |

Nunca coloque esses valores direto no código ou no YAML.

---

## 4. Ativar o GitHub Pages

**Settings → Pages → Build and deployment → Source: "GitHub Actions"**
(não "Deploy from a branch" — esse modo antigo não funciona com o job
`deploy` deste workflow). Depois disso, a página atualiza sozinha a cada
execução, em `https://SEU-USUARIO.github.io/SEU-REPO/`.

---

## 5. Configurar o Teams (opcional)

O Incoming Webhook clássico foi desativado pela Microsoft em 05/2026. Use
o app **Workflows**:

1. No canal do Teams: **⋯ → Workflows**.
2. Escolha o modelo **"Postar em um canal quando uma solicitação de webhook
   for recebida"**.
3. Confirme Time/Canal e copie a URL gerada → secret `TEAMS_WEBHOOK_URL`.
4. Teste: `curl -X POST "URL" -H "Content-Type: application/json" -d '{"text":"teste"}'`.

Se a política de TI bloquear webhooks, use e-mail (`NOTIFY_METHOD=email`
em `monitor-dou.yml`, já implementado em `email_notifier.py`) — vantagem
extra: permite anexar o `.docx` de verdade, o que o Teams não permite.

---

## 6. Rodar localmente

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # preencha INLABS_EMAIL/INLABS_SENHA
python -m src.main
```

Deixe `TEAMS_WEBHOOK_URL` vazio para testar sem notificar — o relatório e
a página HTML são gerados normalmente mesmo assim.

---

## 7. Deploy e teste no GitHub Actions

1. Após configurar Secrets (seção 3) e Pages (seção 4), vá em **Actions**.
2. Selecione o workflow e clique em **"Run workflow"** (não precisa
   esperar as 8h).
3. Confira: `.docx` commitado em `reports/`, página do Pages atualizada, e
   (se configurado) mensagem no Teams.

---

## 8. Troubleshooting

**Deployment failed, try again later (job `deploy`)**
Geralmente falha transitória do GitHub Pages, ou dois deploys rodando ao
mesmo tempo (reexecuções manuais em sequência). Adicione um `concurrency`
group no job `deploy` e evite disparar o workflow várias vezes seguidas.
Confirme também que o Source em Settings → Pages está em "GitHub Actions".

**`RemoteDisconnected` / falha ao acessar o INLABS**
Instabilidade pontual do serviço. A automação já tenta 3x e, se falhar,
publica uma página de aviso em vez de travar. Normalmente resolve sozinho
na execução seguinte.

**Aparecem publicações de outros ministérios**
Confira se `DOU_KEYWORDS` contém os nomes completos do órgão (não
abreviações genéricas demais) — o filtro compara apenas o campo de órgão
publicador, não o texto do artigo.

**Link "Abrir no DOU" não abre o artigo direto**
O INLABS não documenta publicamente qual campo do XML carrega o slug
usado nas URLs do site. Enquanto isso não é confirmado, o link aponta para
uma busca já filtrada por MDIC/Inmetro (sempre funciona). Para investigar,
ative `DOU_DEBUG_XML_ATTRS=true` no workflow e inspecione os atributos
logados na próxima execução.

**Erro de autenticação SMTP**
Confirme com a TI se a conta exige "senha de aplicativo" (comum em
Microsoft 365/Exchange) em vez da senha normal.
