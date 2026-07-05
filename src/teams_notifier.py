"""
Envio da notificação diária para o Microsoft Teams.

ATENÇÃO — leia antes de configurar o webhook:
O "Incoming Webhook" clássico do Teams (Conector do Office 365) foi
DESATIVADO pela Microsoft entre 18 e 22/05/2026. Se o MDIC ainda tiver um
webhook clássico configurado, ele já não funciona mais.

O substituto oficial é o app "Workflows" (Power Automate) dentro do Teams,
usando o modelo "Postar em um canal quando uma solicitação de webhook for
recebida". Do ponto de vista deste script, a diferença é só a URL: você
ainda faz um POST de um JSON simples {"text": "..."} para uma URL. Veja o
passo a passo completo para gerar essa URL no README.md.

O webhook (clássico ou via Workflow) NÃO permite anexar arquivos binários —
apenas texto/HTML simples. Por isso enviamos um resumo das publicações do
dia + um link para o relatório .docx completo, que fica salvo no próprio
repositório do GitHub (pasta reports/).
"""
from __future__ import annotations

import logging
from typing import List, Optional

import requests

from .dou_client import Publicacao

logger = logging.getLogger(__name__)

# Evita mensagens gigantes no Teams; a lista completa sempre está no .docx.
MAX_ITEMS_IN_MESSAGE = 15


class TeamsNotificationError(Exception):
    """Erro ao enviar a notificação para o Teams."""


def _build_message_text(
    publicacoes: List[Publicacao],
    reference_date_str: str,
    report_link: Optional[str],
) -> str:
    lines = [
        f"📰 **Monitoramento Diário DOU - MDIC/Inmetro** ({reference_date_str})",
        "",
    ]

    if not publicacoes:
        lines.append("Nenhuma publicação mencionando MDIC ou Inmetro foi encontrada hoje.")
    else:
        lines.append(f"**{len(publicacoes)} publicação(ões) encontrada(s):**")
        lines.append("")
        for pub in publicacoes[:MAX_ITEMS_IN_MESSAGE]:
            lines.append(
                f"- **{pub.orgao}** — {pub.titulo} (Ato nº {pub.numero_ato}) "
                f"— [Ver no DOU]({pub.link})"
            )
        if len(publicacoes) > MAX_ITEMS_IN_MESSAGE:
            restantes = len(publicacoes) - MAX_ITEMS_IN_MESSAGE
            lines.append(
                f"- ... e mais {restantes} publicação(ões). Veja a lista completa "
                f"no relatório em Word."
            )

    lines.append("")
    if report_link:
        lines.append(f"📄 [Baixar relatório completo em Word]({report_link})")
    else:
        lines.append(
            "📄 Relatório completo em Word gerado e salvo no repositório do "
            "GitHub (pasta `reports/`)."
        )

    return "\n\n".join(lines)


def send_teams_message(
    webhook_url: str,
    publicacoes: List[Publicacao],
    reference_date_str: str,
    report_link: Optional[str] = None,
    timeout: int = 30,
    max_retries: int = 3,
) -> None:
    """Envia a mensagem diária. Levanta TeamsNotificationError em caso de falha
    definitiva (depois de esgotar as tentativas)."""
    if not webhook_url:
        raise TeamsNotificationError(
            "TEAMS_WEBHOOK_URL não configurado (verifique os GitHub Secrets)."
        )

    payload = {"text": _build_message_text(publicacoes, reference_date_str, report_link)}

    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=timeout)
            if resp.status_code in (200, 202):
                logger.info("Mensagem enviada ao Teams com sucesso (tentativa %s).", attempt)
                return
            last_error = RuntimeError(f"Teams respondeu {resp.status_code}: {resp.text[:300]}")
        except requests.RequestException as exc:
            last_error = exc
        logger.warning(
            "Tentativa %s/%s de enviar ao Teams falhou: %s", attempt, max_retries, last_error
        )

    raise TeamsNotificationError(
        f"Não foi possível enviar a notificação ao Teams após {max_retries} "
        f"tentativas: {last_error}"
    )


def send_teams_alert(webhook_url: str, message: str, timeout: int = 30) -> None:
    """Envia um alerta simples (ex.: falha ao consultar o DOU). Usado pelo
    main.py para garantir que problemas nunca fiquem em silêncio. Nunca
    levanta exceção — é 'best effort', pois já estamos no caminho de erro."""
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json={"text": f"⚠️ {message}"}, timeout=timeout)
    except requests.RequestException:
        logger.exception("Falha ao enviar alerta de erro para o Teams.")
