"""
Configurações centrais da automação de monitoramento do DOU.

Todas as configurações sensíveis (URL do webhook do Teams, credenciais de
e-mail) devem vir de variáveis de ambiente / GitHub Secrets.
NUNCA coloque valores reais diretamente neste arquivo.
"""
import os

# ---------------------------------------------------------------------------
# Fonte de dados no Diário Oficial da União
# ---------------------------------------------------------------------------
# Seções do DOU: do1 (atos normativos), do2 (atos de pessoal), do3 (contratos,
# editais, avisos). O pedido original é sobre a Seção 2.
DOU_SECAO = os.getenv("DOU_SECAO", "do2")

# IMPORTANTE (corrigido em 05/07/2026): estes nomes são usados para
# filtrar pelo ÓRGÃO PUBLICADOR do ato (equivalente aos parâmetros
# "org"/"org_sub" do link oficial de busca do DOU), e NÃO por menções no
# texto do artigo. Isso evita trazer publicações de outros ministérios
# que apenas citam o MDIC/Inmetro de passagem (ex.: cessão de servidor).
DOU_KEYWORDS = [
    kw.strip()
    for kw in os.getenv(
        "DOU_KEYWORDS",
        "MDIC,Ministério do Desenvolvimento, Indústria, Comércio e Serviços,"
        "Inmetro,Instituto Nacional de Metrologia, Qualidade e Tecnologia",
    ).split(",")
    if kw.strip()
]

# Ativa logs com os atributos brutos de cada <article> do XML do INLABS.
# Usado temporariamente para confirmar qual campo carrega o link/slug
# amigável do artigo (ver nota em dou_client.py sobre o link "Abrir no
# DOU"). Depois de confirmado o campo certo, pode voltar para "false".
DOU_DEBUG_XML_ATTRS = os.getenv("DOU_DEBUG_XML_ATTRS", "false").lower() == "true"

# ---------------------------------------------------------------------------
# INLABS — fonte oficial de dados do DOU para automações (ver dou_client.py)
# ---------------------------------------------------------------------------
INLABS_EMAIL = os.getenv("INLABS_EMAIL", "")
INLABS_SENHA = os.getenv("INLABS_SENHA", "")

# ---------------------------------------------------------------------------
# Saída (relatório Word)
# ---------------------------------------------------------------------------
REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")

# Pasta usada pelo GitHub Pages para publicar a página HTML pública do
# monitoramento (ver src/html_generator.py). O GitHub Pages, quando
# configurado com "Source: GitHub Actions" (ver README), serve
# automaticamente o conteúdo desta pasta em
# https://SEU-USUARIO.github.io/SEU-REPO/
DOCS_DIR = os.getenv("DOCS_DIR", "docs")

# ---------------------------------------------------------------------------
# Notificação
# ---------------------------------------------------------------------------
# Valores possíveis: "teams", "email" ou "teams,email" (envia pelos dois
# canais). Veja README.md para decidir qual usar no ambiente do MDIC.
NOTIFY_METHOD = os.getenv("NOTIFY_METHOD", "teams")

# URL gerada pelo app "Workflows" do Teams (substituto do Incoming Webhook
# clássico, que foi desativado pela Microsoft em maio/2026). Veja o
# passo a passo no README.md.
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")

# Fallback por e-mail via SMTP institucional (usado se webhooks não forem
# liberados pela política de segurança do MDIC).
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT") or "587")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)
EMAIL_TO = [addr.strip() for addr in os.getenv("EMAIL_TO", "").split(",") if addr.strip()]

# ---------------------------------------------------------------------------
# Link para o relatório completo, usado na mensagem do Teams (o webhook não
# permite anexar arquivos binários — ver README, seção "Perguntas
# respondidas"). Essas variáveis são preenchidas automaticamente pelo
# GitHub Actions; em execução local ficam em branco.
# ---------------------------------------------------------------------------
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
GITHUB_SERVER_URL = os.getenv("GITHUB_SERVER_URL", "https://github.com")
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME", "main")

# ---------------------------------------------------------------------------
# Robustez de rede
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
