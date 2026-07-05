"""
Fallback de notificação por e-mail via SMTP institucional.

Use este caminho se a criação/uso de webhooks (ou do app Workflows) no
Teams não for permitida pela política de segurança do MDIC. Diferente do
Teams, o e-mail permite anexar o arquivo .docx de verdade.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


class EmailNotificationError(Exception):
    """Erro ao enviar a notificação por e-mail."""


def send_email_report(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    use_tls: bool,
    email_from: str,
    email_to: List[str],
    subject: str,
    body_text: str,
    attachment_path: Optional[Union[str, Path]] = None,
    timeout: int = 30,
) -> None:
    if not smtp_host or not email_to:
        raise EmailNotificationError(
            "SMTP_HOST e/ou EMAIL_TO não configurados (verifique os GitHub Secrets)."
        )

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = ", ".join(email_to)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    if attachment_path and Path(attachment_path).exists():
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=Path(attachment_path).name)
        part["Content-Disposition"] = f'attachment; filename="{Path(attachment_path).name}"'
        msg.attach(part)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout) as server:
            if use_tls:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_password)
            server.sendmail(email_from, email_to, msg.as_string())
        logger.info("E-mail enviado com sucesso para %s.", email_to)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailNotificationError(f"Falha ao enviar e-mail via SMTP: {exc}") from exc
