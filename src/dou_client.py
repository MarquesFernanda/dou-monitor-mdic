from __future__ import annotations

import io
import logging
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote
from xml.etree import ElementTree

import holidays
import requests


BRASILIA_TZ = timezone(timedelta(hours=-3))

logger = logging.getLogger(__name__)

INLABS_LOGIN_URL = "https://inlabs.in.gov.br/logar.php"
INLABS_DOWNLOAD_URL = "https://inlabs.in.gov.br/index.php"
INLABS_LEITURA_URL = "https://www.in.gov.br/leiturajornal"
INLABS_SESSION_COOKIE_NAME = "inlabs_session_cookie"

USER_AGENT = (
    "MonitoramentoDOU-MDIC/1.0 "
    "(automacao interna de clipping do DOU via INLABS; 1 consulta/dia)"
)

BR_HOLIDAYS = holidays.Brazil()


_ATTR_TITULO = ("name", "title", "titulo", "ementa")
_ATTR_ORGAO = ("artCategory", "pubName", "hierarchyStr", "orgao", "displayName")
_ATTR_TIPO = ("artType", "tipo", "identifica")
_ATTR_NUMERO = ("numberDocument", "artNumber", "numero")
_ATTR_ID = ("id", "idMateria", "identifica")

_ATTR_SLUG = ("urlTitle", "friendlyUrl", "slug", "idOficial", "pdfPage")


DEFAULT_ORG_KEYWORDS = (
    "Ministério do Desenvolvimento, Indústria, Comércio e Serviços",
    "Instituto Nacional de Metrologia, Qualidade e Tecnologia",
    "Inmetro",
    "MDIC",
)


class DouUnavailableError(Exception):
    """Erro ao consultar o DOU (via INLABS) depois de todas as tentativas."""


class InlabsAuthError(DouUnavailableError):
    """Erro de autenticação no INLABS (e-mail/senha incorretos ou expirados)."""


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
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def get_reference_date(today: Optional[date] = None) -> date:
    
    ref = today or datetime.now(BRASILIA_TZ).date()
    while ref.weekday() >= 5 or ref in BR_HOLIDAYS:  # 5 = sábado, 6 = domingo
        ref -= timedelta(days=1)
    return ref


def _login(session: requests.Session, email: str, password: str, timeout: int) -> str:
    """Autentica no INLABS e retorna o valor do cookie de sessão."""
    if not email or not password:
        raise InlabsAuthError(
            "INLABS_EMAIL/INLABS_SENHA não configurados (verifique os GitHub Secrets)."
        )
    resp = session.post(
        INLABS_LOGIN_URL,
        data={"email": email, "password": password},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": USER_AGENT,
        },
        timeout=timeout,
    )
    cookie_value = session.cookies.get(INLABS_SESSION_COOKIE_NAME)
    if resp.status_code >= 400 or not cookie_value:
        raise InlabsAuthError(
            f"Falha ao autenticar no INLABS (status {resp.status_code}). "
            "Confira o e-mail/senha configurados nos GitHub Secrets "
            "INLABS_EMAIL e INLABS_SENHA."
        )
    return cookie_value


def _download_zip(
    session: requests.Session,
    cookie_value: str,
    reference_date: date,
    secao: str,
    timeout: int,
) -> bytes:
    data_completa = reference_date.strftime("%Y-%m-%d")
    secao_upper = secao.upper()
    nome_arquivo = f"{data_completa}-{secao_upper}.zip"
    resp = session.get(
        INLABS_DOWNLOAD_URL,
        params={"p": data_completa, "dl": nome_arquivo},
        headers={
            "Cookie": f"{INLABS_SESSION_COOKIE_NAME}={cookie_value}",
            "origem": "736372697074",
            "User-Agent": USER_AGENT,
        },
        timeout=timeout,
    )
    if resp.status_code == 404:
        raise DouUnavailableError(
            f"O INLABS não encontrou edição para {nome_arquivo} "
            f"(pode não ter havido publicação nessa seção/data)."
        )
    resp.raise_for_status()
    if resp.content[:2] != b"PK":
        raise DouUnavailableError(
            f"O INLABS não retornou um arquivo .zip válido para {nome_arquivo}."
        )
    return resp.content


def _first_present(elem, *keys: str, default: str = "") -> str:
    for key in keys:
        value = elem.get(key)
        if value:
            return str(value)
    return default


def _extract_text(elem) -> str:
    return " ".join(t.strip() for t in elem.itertext() if t and t.strip())


def _build_search_link(reference_date: date, secao: str) -> str:
    org = quote("Ministério do Desenvolvimento, Indústria, Comércio e Serviços")
    org_sub = quote("Instituto Nacional de Metrologia, Qualidade e Tecnologia")
    data_str = reference_date.strftime("%d-%m-%Y")
    return (
        f"{INLABS_LEITURA_URL}?data={data_str}&secao={secao}"
        f"&org={org}&org_sub={org_sub}#daypicker"
    )


def _normalize(
    xml_bytes: bytes,
    reference_date: date,
    secao: str,
    debug_attrs: bool = False,
) -> Optional[Publicacao]:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        logger.warning("Um dos arquivos XML do INLABS não pôde ser lido (ignorado).")
        return None

    
    article = root if root.tag.lower().endswith("article") else root.find(".//article")
    if article is None:
        article = root

    if debug_attrs:
        logger.info("DEBUG atributos do <article>: %s", dict(article.attrib))

    titulo = _first_present(article, *_ATTR_TITULO)
    orgao = _first_present(article, *_ATTR_ORGAO)
    tipo_ato = _first_present(article, *_ATTR_TIPO)
    numero_ato = _first_present(article, *_ATTR_NUMERO, default="s/nº")
    art_id = _first_present(article, *_ATTR_ID)
    slug = _first_present(article, *_ATTR_SLUG)

    corpo_texto = _extract_text(article)
    if not titulo:
        titulo = corpo_texto[:200] if corpo_texto else "(sem título)"

    if slug:
        link = f"https://www.in.gov.br/web/dou/-/{slug}"
    else:
        link = _build_search_link(reference_date, secao)

    return Publicacao(
        data_publicacao=reference_date.strftime("%d/%m/%Y"),
        orgao=orgao or "Não identificado",
        titulo=titulo,
        tipo_ato=tipo_ato or "-",
        numero_ato=numero_ato,
        link=link,
        raw={"xml_len": len(xml_bytes), "texto": corpo_texto[:2000], "art_id": art_id},
    )


def _matches_keywords(pub: Publicacao, org_keywords: list) -> bool:
    """Filtra pelo ÓRGÃO PUBLICADOR (quem publicou o ato), não pelo texto
    do artigo. Isso evita falsos positivos como uma portaria de pessoal
    de outro ministério que apenas cita o MDIC/Inmetro de passagem (ex.:
    cessão de servidor)."""
    haystack = _strip_accents(pub.orgao).lower()
    return any(_strip_accents(kw).lower() in haystack for kw in org_keywords)


def search_dou(
    keywords: list,
    secao: str = "do2",
    reference_date: Optional[date] = None,
    max_retries: int = 3,
    timeout: int = 30,
    inlabs_email: str = "",
    inlabs_password: str = "",
    debug_xml_attrs: bool = False,
):
    
    ref_date = reference_date or get_reference_date()

    last_error: Optional[Exception] = None
    zip_bytes: Optional[bytes] = None
    for attempt in range(1, max_retries + 1):
        try:
            session = requests.Session()
            cookie_value = _login(session, inlabs_email, inlabs_password, timeout)
            zip_bytes = _download_zip(session, cookie_value, ref_date, secao, timeout)
            break
        except InlabsAuthError:
            
            raise
        except (requests.RequestException, DouUnavailableError) as exc:
            last_error = exc
            logger.warning(
                "Tentativa %s/%s de acessar o INLABS falhou: %s", attempt, max_retries, exc
            )
    if zip_bytes is None:
        raise DouUnavailableError(
            f"Não foi possível acessar o INLABS após {max_retries} tentativas: {last_error}"
        )

    all_pubs = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".xml"):
                continue
            pub = _normalize(zf.read(name), ref_date, secao, debug_attrs=debug_xml_attrs)
            if pub is not None:
                all_pubs.append(pub)

    filtered = [pub for pub in all_pubs if _matches_keywords(pub, keywords)]

    logger.info(
        "DOU %s (INLABS): %s publicações na seção '%s', %s após filtro de órgão (MDIC/Inmetro).",
        ref_date, len(all_pubs), secao, len(filtered),
    )
    return ref_date, filtered