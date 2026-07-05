"""
Ponto de entrada da automação de monitoramento do DOU (MDIC/Inmetro).

Uso local:
    python -m src.main

Em produção, é executado pelo GitHub Actions (veja
.github/workflows/monitor-dou.yml).

Variáveis de ambiente relevantes: veja src/config.py e .env.example.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

# Carrega variáveis de um arquivo .env se ele existir (só é usado para rodar
# localmente; no GitHub Actions as variáveis vêm dos Secrets e este bloco
# simplesmente não encontra o arquivo e não faz nada).
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from . import config
from .dou_client import DouUnavailableError, search_dou
from .email_notifier import EmailNotificationError, send_email_report
from .html_generator import generate_html_page
from .report_generator import generate_report
from .teams_notifier import TeamsNotificationError, send_teams_alert, send_teams_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def _build_report_link(filename: str) -> Optional[str]:
    """Monta o link do relatório dentro do repositório do GitHub.

    Só funciona de verdade se quem for abrir o link também tiver acesso ao
    repositório no GitHub (ou seja, se o repo for público, ou se todos os
    destinatários no Teams também tiverem conta/acesso ao GitHub da
    organização). Por isso o resumo completo já vai no corpo da mensagem do
    Teams — este link é um "extra" para quem quiser o .docx formatado.
    """
    if not config.GITHUB_REPOSITORY:
        return None
    return (
        f"{config.GITHUB_SERVER_URL}/{config.GITHUB_REPOSITORY}/blob/"
        f"{config.GITHUB_REF_NAME}/{config.REPORTS_DIR}/{filename}"
    )


def run() -> int:
    methods = [m.strip().lower() for m in config.NOTIFY_METHOD.split(",") if m.strip()]

    # 1) Buscar as publicações do dia no DOU -------------------------------
    try:
        reference_date, publicacoes = search_dou(
            keywords=config.DOU_KEYWORDS,
            secao=config.DOU_SECAO,
            max_retries=config.MAX_RETRIES,
            timeout=config.REQUEST_TIMEOUT,
        )
    except DouUnavailableError as exc:
        logger.error("Falha ao consultar o DOU: %s", exc)
        # Nunca falha em silêncio: avisa no Teams que a checagem de hoje
        # não pôde ser concluída, para alguém verificar manualmente.
        if "teams" in methods:
            send_teams_alert(
                config.TEAMS_WEBHOOK_URL,
                f"O monitoramento do DOU falhou hoje: {exc}. "
                f"Verifique manualmente em https://www.in.gov.br/leiturajornal",
            )
        return 1

    # 2) Gerar o relatório em Word ------------------------------------------
    filename = f"relatorio_dou_mdic_{reference_date.isoformat()}.docx"
    output_path = f"{config.REPORTS_DIR}/{filename}"

    try:
        generate_report(publicacoes, reference_date, output_path)
    except Exception:
        logger.exception("Falha inesperada ao gerar o relatório em Word.")
        raise

    report_link = _build_report_link(filename)
    reference_date_str = reference_date.strftime("%d/%m/%Y")
    exit_code = 0

    # 2.1) Gerar/atualizar a página HTML pública (GitHub Pages) -----------
    # Essa é a via simples de consulta: não depende de Teams nem de TI,
    # só do link da página, que fica sempre no mesmo endereço.
    try:
        generate_html_page(
            publicacoes,
            reference_date,
            docs_dir=config.DOCS_DIR,
            docx_link=report_link,
        )
    except Exception:
        logger.exception("Falha ao gerar a página HTML (docs/index.html).")

    # 3) Notificar --------------------------------------------------------
    if "teams" in methods:
        try:
            send_teams_message(
                config.TEAMS_WEBHOOK_URL, publicacoes, reference_date_str, report_link
            )
        except TeamsNotificationError as exc:
            logger.error("Falha ao notificar o Teams: %s", exc)
            exit_code = 1

    if "email" in methods:
        try:
            send_email_report(
                smtp_host=config.SMTP_HOST,
                smtp_port=config.SMTP_PORT,
                smtp_user=config.SMTP_USER,
                smtp_password=config.SMTP_PASSWORD,
                use_tls=config.SMTP_USE_TLS,
                email_from=config.EMAIL_FROM,
                email_to=config.EMAIL_TO,
                subject=f"Monitoramento Diário DOU - MDIC/Inmetro ({reference_date_str})",
                body_text=(
                    f"Segue em anexo o relatório de {reference_date_str}. "
                    f"{len(publicacoes)} publicação(ões) encontrada(s)."
                ),
                attachment_path=output_path,
            )
        except EmailNotificationError as exc:
            logger.error("Falha ao enviar e-mail: %s", exc)
            exit_code = 1

    logger.info(
        "Execução concluída. Data de referência: %s. Publicações encontradas: %s.",
        reference_date_str,
        len(publicacoes),
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(run())