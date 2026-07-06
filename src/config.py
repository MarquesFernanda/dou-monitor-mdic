import os

DOU_SECAO = os.getenv("DOU_SECAO", "do2")


DOU_KEYWORDS = [
    kw.strip()
    for kw in os.getenv(
        "DOU_KEYWORDS",
        "MDIC;Ministério do Desenvolvimento, Indústria, Comércio e Serviços;"
        "Inmetro;Instituto Nacional de Metrologia, Qualidade e Tecnologia",
    ).split(";")
    if kw.strip()
]


DOU_DEBUG_XML_ATTRS = os.getenv("DOU_DEBUG_XML_ATTRS", "false").lower() == "true"

INLABS_EMAIL = os.getenv("INLABS_EMAIL", "")
INLABS_SENHA = os.getenv("INLABS_SENHA", "")

REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")
DOCS_DIR = os.getenv("DOCS_DIR", "docs")

NOTIFY_METHOD = os.getenv("NOTIFY_METHOD", "teams")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT") or "587")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)
EMAIL_TO = [addr.strip() for addr in os.getenv("EMAIL_TO", "").split(",") if addr.strip()]

GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
GITHUB_SERVER_URL = os.getenv("GITHUB_SERVER_URL", "https://github.com")
GITHUB_REF_NAME = os.getenv("GITHUB_REF_NAME", "main")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))