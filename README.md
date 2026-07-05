# Monitoramento Diário DOU — MDIC / Inmetro

Automação que roda todo dia às 8h (Brasília) via GitHub Actions, consulta o
Diário Oficial da União (Seção 2) em busca de publicações do MDIC e do
Inmetro, gera um relatório em Word e avisa a equipe no Microsoft Teams.

> **Aviso importante antes de começar**
> O "Incoming Webhook" clássico do Teams (o que normalmente aparece em
> tutoriais antigos) foi **desativado pela Microsoft entre 18 e 22/05/2026**.
> Se você já tinha um webhook desse tipo configurado, ele parou de
> funcionar. O passo a passo abaixo já usa o substituto oficial: o app
> **Workflows** (Power Automate) dentro do Teams. Para quem escreve o
> código, muda muito pouco — ainda é só um POST de JSON para uma URL.

---

## Sumário

1. [Como a automação funciona](#1-como-a-automação-funciona)
2. [Perguntas respondidas](#2-perguntas-respondidas)
3. [Estrutura do repositório](#3-estrutura-do-repositório)
4. [Passo a passo: criar o repositório no GitHub](#4-passo-a-passo-criar-o-repositório-no-github)
5. [Passo a passo: configurar o Teams](#5-passo-a-passo-configurar-o-teams)
6. [O ambiente é institucional (MDIC) — o que verificar antes](#6-o-ambiente-é-institucional-mdic--o-que-verificar-antes)
7. [Alternativas se o webhook não for permitido](#7-alternativas-se-o-webhook-não-for-permitido)
8. [Configurar os GitHub Secrets](#8-configurar-os-github-secrets)
9. [Rodar localmente para testar antes de subir](#9-rodar-localmente-para-testar-antes-de-subir)
10. [Deploy e teste no GitHub Actions](#10-deploy-e-teste-no-github-actions)
11. [Segurança do webhook](#11-segurança-do-webhook)
12. [Troubleshooting](#12-troubleshooting)
13. [Evoluindo a fonte de dados (INLABS)](#13-evoluindo-a-fonte-de-dados-inlabs)

---

## 1. Como a automação funciona

```
GitHub Actions (todo dia, 8h de Brasília)
        │
        ▼
src/main.py
        │
        ├─► src/dou_client.py     → busca no DOU (Seção 2) e filtra MDIC/Inmetro
        ├─► src/report_generator.py → gera relatorio_dou_mdic_AAAA-MM-DD.docx
        └─► src/teams_notifier.py   → posta resumo + link no Teams
             (ou src/email_notifier.py, se você configurar o fallback por e-mail)
```

O relatório `.docx` gerado também é commitado de volta no repositório
(pasta `reports/`), servindo como histórico e como backup caso a
notificação falhe.

---

## 2. Perguntas respondidas

**Qual é a URL oficial da API da Imprensa Nacional para consultar o DOU?**
Não existe uma API REST pública e documentada para terceiros. A Imprensa
Nacional colocou inclusive um bot manager (Cloudflare) que dificulta
consultas automatizadas ao buscador `in.gov.br/consulta`. A alternativa que
esta automação usa é ler a mesma página pública que você já usa no
navegador (`in.gov.br/leiturajornal?data=...&secao=do2`) e extrair os dados
que a própria página carrega. É o mesmo princípio usado por ferramentas
open-source de referência nesse tema, como o **Ro-DOU** (mantido por
órgãos do governo). Se essa via ficar instável no futuro, o caminho mais
robusto — mas que exige cadastro gratuito — é o **INLABS**
(`inlabs.in.gov.br`), serviço oficial da Imprensa Nacional com XML/PDF
completos de cada edição. Veja a seção 13.

**O webhook do Teams permite anexar arquivos?**
Não — nem o antigo Incoming Webhook, nem o novo Workflow. Ambos só recebem
JSON com texto (e, no caso do Workflow, Adaptive Cards). Por isso a
automação: (1) manda o resumo das publicações **direto no texto** da
mensagem do Teams (então ninguém depende de abrir um link para saber o que
saiu), e (2) manda também um link para o `.docx` completo, salvo no
repositório do GitHub, para quem quiser o documento formatado.

**Existe limite de tamanho para a mensagem?**
Sim, o payload de texto tem um limite prático de cerca de 28 KB. O código já
corta a lista em 15 itens na mensagem (configurável em
`MAX_ITEMS_IN_MESSAGE` em `src/teams_notifier.py`) e sempre aponta para o
`.docx` completo quando há mais publicações que isso.

---

## 3. Estrutura do repositório

```
dou-monitor-mdic/
├── .github/workflows/monitor-dou.yml   ← workflow do GitHub Actions
├── src/
│   ├── __init__.py
│   ├── config.py            ← todas as configurações (lidas de variáveis de ambiente)
│   ├── dou_client.py        ← busca e filtra publicações no DOU
│   ├── report_generator.py  ← gera o .docx
│   ├── teams_notifier.py    ← envia para o Teams
│   ├── email_notifier.py    ← envia por e-mail (fallback)
│   └── main.py              ← orquestra tudo (ponto de entrada)
├── reports/                 ← relatórios .docx gerados (histórico)
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 4. Passo a passo: criar o repositório no GitHub

1. Acesse [github.com/new](https://github.com/new).
2. Dê um nome, por exemplo `dou-monitor-mdic`.
3. Marque como **Private** (recomendado — o repositório vai guardar o
   histórico de relatórios; se contiver informação sensível, privado é mais
   seguro).
4. **Não** marque para criar README/`.gitignore` automaticamente (já temos
   os nossos).
5. Clique em "Create repository".
6. No seu computador, dentro da pasta com todos os arquivos deste projeto:

   ```bash
   git init
   git add .
   git commit -m "Automação de monitoramento do DOU - MDIC/Inmetro"
   git branch -M main
   git remote add origin https://github.com/SEU-USUARIO/dou-monitor-mdic.git
   git push -u origin main
   ```

   (Substitua `SEU-USUARIO` pelo seu usuário ou organização no GitHub.)

---

## 5. Passo a passo: configurar o Teams

Como o Incoming Webhook clássico foi desativado, use o app **Workflows**:

1. No Microsoft Teams, abra o **canal** onde as notificações devem chegar.
2. Clique nos **três pontinhos (⋯)** ao lado do nome do canal → **Workflows**.
3. Procure o modelo **"Postar em um canal quando uma solicitação de webhook
   for recebida"** (em inglês: *"Post to a channel when a webhook request is
   received"`) e selecione-o.
4. Faça login/autorize com sua conta institucional, se solicitado.
5. Confirme o **Time** e o **Canal** de destino.
6. Ao final, o Teams vai gerar uma **URL única**. Copie essa URL — é ela
   que vai virar o secret `TEAMS_WEBHOOK_URL` (veja seção 8).
7. Dê um nome ao workflow (ex.: `Monitoramento DOU MDIC`) e salve.

> Dica: depois de criado, você pode testar rapidinho rodando no terminal
> (troque a URL pela sua):
> ```bash
> curl -X POST "SUA_URL_AQUI" -H "Content-Type: application/json" \
>   -d '{"text": "Teste de conexão da automação do DOU ✅"}'
> ```
> Se aparecer a mensagem no canal, está funcionando.

---

## 6. O ambiente é institucional (MDIC) — o que verificar antes

Ambientes corporativos costumam restringir a criação de conectores/workflows
por política de segurança (Teams Admin Center / Power Platform Admin
Center). Antes de assumir que vai funcionar:

- **Peça para o administrador de TI/Teams do MDIC verificar** se o app
  **Workflows** está liberado para o seu usuário/time (no Teams Admin
  Center: *Teams apps → Manage apps → procurar "Workflows"*, e no Power
  Platform Admin Center: políticas de *Data Loss Prevention* que possam
  bloquear o conector "Teams" ou "HTTP").
- Se você **não tiver permissão para criar o workflow você mesmo**, não
  tem problema: **peça para a TI criar o workflow e apenas te repassar a
  URL gerada**. O desenvolvedor só precisa dessa URL para colocar no
  GitHub Secret — não precisa de acesso administrativo a nada.
- Se a política de segurança **bloquear qualquer webhook/workflow** de
  saída, use uma das alternativas da seção 7.

---

## 7. Alternativas se o webhook não for permitido

### Opção A — E-mail via SMTP institucional (recomendada como alternativa)

Já está implementada em `src/email_notifier.py`. Ela manda o `.docx` **como
anexo de verdade** (algo que o Teams nem permite). Para usar:

1. Peça à TI as credenciais/servidor SMTP institucional (host, porta,
   usuário, senha ou política de autenticação).
2. Configure os secrets `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
   `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` (seção 8).
3. Mude `NOTIFY_METHOD` para `email` (ou `teams,email` para usar os dois)
   no arquivo `.github/workflows/monitor-dou.yml`.

### Opção B — Salvar em uma pasta do SharePoint

Mais avançado: exige registrar um "app" no Azure AD (Microsoft Entra ID)
com permissão `Files.ReadWrite` no Microsoft Graph, para o script poder
fazer upload do `.docx` numa biblioteca de documentos do SharePoint/Teams.
Isso normalmente precisa de aprovação da TI para criar o app registration.
Se quiser seguir por aqui, me avise que eu monto o módulo
`sharepoint_notifier.py` equivalente aos outros — não incluí por padrão
porque exige uma configuração de TI mais pesada que a maioria dos times
não tem de imediato.

### Opção C — Só o histórico no GitHub

Mesmo sem Teams ou e-mail, o relatório `.docx` sempre é commitado na pasta
`reports/` do repositório — então, na pior das hipóteses, dá para consultar
manualmente lá.

---

## 8. Configurar os GitHub Secrets

No repositório: **Settings → Secrets and variables → Actions → New
repository secret**. Crie:

| Secret               | Obrigatório | Descrição                                                        |
|-----------------------|:-----------:|-------------------------------------------------------------------|
| `TEAMS_WEBHOOK_URL`   | Se usar Teams | URL gerada no passo 5                                            |
| `SMTP_HOST`           | Se usar e-mail | Servidor SMTP institucional                                     |
| `SMTP_PORT`           | Se usar e-mail | Normalmente `587`                                                |
| `SMTP_USER`           | Se usar e-mail | Usuário/e-mail de autenticação                                   |
| `SMTP_PASSWORD`       | Se usar e-mail | Senha (ou senha de aplicativo)                                   |
| `EMAIL_FROM`          | Se usar e-mail | Endereço remetente                                                |
| `EMAIL_TO`            | Se usar e-mail | Destinatários separados por vírgula                               |

**Nunca** coloque esses valores direto no código ou no arquivo YAML —
sempre via Secrets, como já está configurado no
`.github/workflows/monitor-dou.yml`.

---

## 9. Rodar localmente para testar antes de subir

Pré-requisitos: Python 3.10+ instalado.

```bash
# 1) Entre na pasta do projeto
cd dou-monitor-mdic

# 2) Crie e ative um ambiente virtual
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3) Instale as dependências
pip install -r requirements.txt

# 4) Configure suas variáveis locais
cp .env.example .env
# edite o .env e cole sua TEAMS_WEBHOOK_URL de teste

# 5) Rode a automação
python -m src.main
```

Se tudo estiver certo, você verá logs no terminal, um arquivo
`reports/relatorio_dou_mdic_AAAA-MM-DD.docx` criado, e a mensagem chegando
no canal do Teams (se `TEAMS_WEBHOOK_URL` estiver configurada).

**Testando sem enviar nada de verdade:** deixe `TEAMS_WEBHOOK_URL` em
branco e `NOTIFY_METHOD=teams` — o script vai gerar o relatório
normalmente e só vai registrar no log o erro de notificação, sem quebrar
nada.

---

## 10. Deploy e teste no GitHub Actions

1. Depois do `git push` (seção 4) e dos Secrets configurados (seção 8), vá
   na aba **Actions** do repositório.
2. Selecione o workflow **"Monitoramento Diário DOU - MDIC/Inmetro"**.
3. Clique em **"Run workflow"** (isso usa o `workflow_dispatch`, então você
   não precisa esperar até 8h para testar).
4. Acompanhe o log de execução. Se algo falhar, o próprio GitHub já marca o
   run como "failed" e (se você tiver notificações por e-mail do GitHub
   ativadas) te avisa.
5. Se tudo der certo, confira: (a) a mensagem chegou no Teams, e (b) o
   arquivo `.docx` foi commitado na pasta `reports/`.

Depois desse teste manual, a automação passa a rodar sozinha todo dia às
11h UTC (8h em Brasília).

---

## 11. Segurança do webhook

- **Nunca** commite a URL do webhook/workflow no código — ela já funciona
  como uma senha (quem tiver a URL consegue postar no canal).
- Use sempre o **GitHub Secret** `TEAMS_WEBHOOK_URL` (seção 8).
- **Rotacione a URL periodicamente**: no Teams, edite o Workflow e gere uma
  nova URL de tempos em tempos (ex.: a cada 6 meses, ou imediatamente se
  suspeitar de vazamento), atualizando o Secret em seguida.
- Restrinja quem tem acesso de **Settings** do repositório no GitHub (só
  quem realmente precisa deve poder ver/editar Secrets — aliás, nem quem
  tem acesso consegue *ler* o valor de um Secret depois de salvo, só
  substituí-lo).

---

## 12. Troubleshooting

**"Nenhum bloco JSON encontrado na página do DOU"**
A Imprensa Nacional pode ter mudado a estrutura da página, ou bloqueado a
requisição (proteção anti-bot). Primeiro teste abrir a URL
`https://www.in.gov.br/leiturajornal?data=DD-MM-AAAA&secao=do2` num
navegador normal para confirmar que a edição existe. Se persistir, veja a
seção 13 (migrar para o INLABS).

**Relatório sempre vem "Nenhuma publicação encontrada", mas eu sei que
saiu algo do MDIC hoje**
Confira se o texto da publicação realmente contém uma das palavras em
`DOU_KEYWORDS` (a comparação é literal, mesmo sendo case-insensitive). Se o
órgão aparecer com outra grafia (ex.: uma sigla diferente), adicione essa
variação em `DOU_KEYWORDS` no workflow YAML.

**A automação não roda no horário agendado**
O `cron` do GitHub Actions pode atrasar alguns minutos em horários de pico
— isso é normal e esperado na infraestrutura compartilhada do GitHub. Se
atrasar muito (>1h) de forma recorrente, rode manualmente via
`workflow_dispatch` enquanto investiga.

**Erro de autenticação SMTP**
Confirme com a TI se a conta usada exige autenticação de dois fatores ou
"senha de aplicativo" específica para SMTP — muitos ambientes corporativos
(Exchange/Microsoft 365) exigem isso em vez da senha normal.

---

## 13. Evoluindo a fonte de dados (INLABS)

Se a leitura da página `leiturajornal` ficar instável no seu ambiente, a
Imprensa Nacional oferece o **INLABS** (`https://inlabs.in.gov.br`) — um
serviço gratuito (desde 2020) com o XML/PDF completo de cada edição do DOU,
exigindo apenas um cadastro simples. É a via usada por ferramentas de
clipping mais robustas (como o Ro-DOU) quando a busca via página fica
bloqueada. Migrar para lá significaria trocar `src/dou_client.py` por um
cliente que baixa o XML do dia e filtra localmente — a interface pública do
módulo (`search_dou(...)` retornando uma lista de `Publicacao`) pode
continuar a mesma, então o resto do projeto (`report_generator.py`,
`teams_notifier.py`, `main.py`) não precisaria mudar. Se quiser, posso
implementar essa versão depois que você validar que a versão atual atende.
