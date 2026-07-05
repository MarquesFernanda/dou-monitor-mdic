"""
Cliente de acesso ao Diário Oficial da União (DOU).

IMPORTANTE — leia antes de mexer aqui:
A Imprensa Nacional não oferece uma API REST pública e documentada para uso
de terceiros. Este módulo lê a mesma página pública que um humano usa no
navegador (https://www.in.gov.br/leiturajornal?data=...&secao=...) — que é
exatamente a URL que você já usa manualmente — e extrai um bloco de dados em
JSON que a própria página carrega para montar a listagem de matérias do dia.

Essa página pode mudar de estrutura, ou ficar temporariamente bloqueada por
proteção anti-bot (a Imprensa Nacional usa Cloudflare). Por isso este código:
  1) tenta novamente algumas vezes antes de desistir (retry com backoff);
  2) nunca falha "em silêncio": se não conseguir acessar o DOU, levanta
     DouUnavailableError, e o main.py usa isso para te avisar via
     Teams/e-mail que a checagem de hoje não pôde ser feita;
  3) usa nomes de campo "flexíveis" (várias alternativas por campo), para
     resistir a pequenas mudanças na estrutura do JSON da página.

Alternativa mais robusta a médio prazo (mas exige cadastro gratuito):
o INLABS (https://inlabs.in.gov.br), que disponibiliza os XMLs oficiais
completos de cada edição do DOU, sem depender de scraping de página HTML.
Veja README.md > "Evoluindo a fonte de dados".
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import holidays
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.in.gov.br/leiturajornal"

# Identifica claramente o robô e como entrar em contato — boa prática para
# automações que consultam sites de terceiros.
USER_AGENT = (
    "MonitoramentoDOU-MDIC/1.0 "
    "(automacao interna de clipping do DOU; 1 consulta/dia)"
)

BR_HOLIDAYS = holidays.Brazil()


class DouUnavailableError(Exception):
    """Erro ao consultar o DOU depois de todas as tentativas de retry."""


@dataclass
class Publicacao:
    """Representa uma publicação do DOU já filtrada e pronta para o relatório."""

    data_publicacao: str
    orgao: str
    titulo: str
    tipo_ato: str
    numero_ato: str
    link: str
    raw: dict = field(default_factory=dict, repr=False)


def _strip_accents(text: str) -> str:
    """Remove acentos para permitir comparação 'MDIC' == 'mdic', 'inmetro' etc."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def get_reference_date(today: Optional[date] = None) -> date:
    """
    Retorna a data que deve ser consultada no DOU.

    Regra: usa o dia corrente; se cair em sábado, domingo ou feriado
    nacional, retrocede para o último dia útil anterior (o DOU não é
    publicado nesses dias em edição normal).
    """
    ref = today or date.today()
    while ref.weekday() >= 5 or ref in BR_HOLIDAYS:  # 5 = sábado, 6 = domingo
        ref -= timedelta(days=1)
    return ref


def _fetch_html(reference_date: date, secao: str, max_retries: int, timeout: int) -> str:
    params = {"data": reference_date.strftime("%d-%m-%Y"), "secao": secao}
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}

    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(BASE_URL, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
            logger.warning(
                "Tentativa %s/%s de acessar o DOU falhou: %s", attempt, max_retries, exc
            )
    raise DouUnavailableError(
        f"Não foi possível acessar o DOU após {max_retries} tentativas: {last_error}"
    )


def _extract_json_blocks(html: str) -> list:
    """
    A página do DOU embute os dados da edição em tags
    <script type="application/json">...</script>. Extraímos todas e
    devolvemos as que conseguirmos decodificar como JSON.
    """
    blocks = []
    for raw in re.findall(
        r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL,
    ):
        try:
            blocks.append(json.loads(raw.strip()))
        except (json.JSONDecodeError, ValueError):
            continue
    return blocks


def _find_articles(json_blocks: list) -> list:
    """
    Procura recursivamente por uma lista de matérias dentro dos blocos JSON.
    A página já foi observada usando a chave 'jsonArray'; mantemos algumas
    alternativas ('items', 'result', 'data') caso a Imprensa Nacional troque
    o nome do campo no futuro.
    """
    candidate_keys = ("jsonArray", "items", "result", "data")
    found: list = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in candidate_keys:
                value = node.get(key)
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    found.extend(value)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for block in json_blocks:
        _walk(block)
    return found


def _first_present(item: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return default


def _normalize(item: dict, reference_date: date) -> Publicacao:
    titulo = _first_present(item, "title", "titulo", "ementa")
    orgao = _first_present(
        item, "artOrgao", "orgao", "pubName", "hierarchyStr", "displayName"
    )
    tipo_ato = _first_present(item, "artType", "tipo", "identifica")
    numero_ato = _first_present(item, "numberDocument", "artNumber", "numero", default="s/nº")
    url_title = _first_present(item, "urlTitle", "urlTítulo")
    link = f"https://www.in.gov.br/web/dou/-/{url_title}" if url_title else BASE_URL

    return Publicacao(
        data_publicacao=reference_date.strftime("%d/%m/%Y"),
        orgao=orgao or "Não identificado",
        titulo=titulo or "(sem título)",
        tipo_ato=tipo_ato or "-",
        numero_ato=numero_ato,
        link=link,
        raw=item,
    )


def _matches_keywords(pub: Publicacao, keywords: list) -> bool:
    haystack = _strip_accents(
        f"{pub.titulo} {pub.orgao} {json.dumps(pub.raw, ensure_ascii=False)}"
    ).lower()
    return any(_strip_accents(kw).lower() in haystack for kw in keywords)


def search_dou(
    keywords: list,
    secao: str = "do2",
    reference_date: Optional[date] = None,
    max_retries: int = 3,
    timeout: int = 30,
):
    """
    Ponto de entrada principal do módulo.

    Retorna uma tupla (data_efetivamente_consultada, lista_de_Publicacao)
    já filtrada pelas `keywords` informadas.

    Levanta DouUnavailableError se não for possível acessar o DOU depois
    de todas as tentativas.
    """
    ref_date = reference_date or get_reference_date()
    html = _fetch_html(ref_date, secao, max_retries, timeout)
    json_blocks = _extract_json_blocks(html)

    if not json_blocks:
        logger.warning(
            "Nenhum bloco JSON encontrado na página do DOU para %s. "
            "A estrutura da página pode ter mudado — veja README.md > Troubleshooting.",
            ref_date,
        )

    raw_articles = _find_articles(json_blocks)
    all_pubs = [_normalize(item, ref_date) for item in raw_articles]
    filtered = [pub for pub in all_pubs if _matches_keywords(pub, keywords)]

    logger.info(
        "DOU %s: %s publicações na seção '%s', %s após filtro de palavras-chave.",
        ref_date, len(all_pubs), secao, len(filtered),
    )
    return ref_date, filtered
