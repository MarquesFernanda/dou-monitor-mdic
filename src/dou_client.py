"""
Cliente de acesso ao Diário Oficial da União (DOU) via INLABS.

HISTÓRICO — por que este módulo mudou:
A primeira versão lia a página pública `in.gov.br/leiturajornal`. Isso
parou de funcionar a partir de servidores como o do GitHub Actions: a
Imprensa Nacional colocou um bot manager (Cloudflare) que bloqueia esse
tipo de acesso, retornando erros 404/502 mesmo com a URL correta.

A solução oficial da própria Imprensa Nacional para automações é o
INLABS (https://inlabs.in.gov.br) — um serviço gratuito (desde 2020) que
exige apenas um cadastro simples (e-mail + senha) e devolve o XML
completo de cada edição, sem bloqueio anti-bot. É a mesma fonte usada por
ferramentas de clipping mais robustas, como o Ro-DOU.

Como funciona o fluxo do INLABS:
  1) POST de login (e-mail/senha) em INLABS_LOGIN_URL -> devolve um cookie
     de sessão.
  2) GET com esse cookie em INLABS_DOWNLOAD_URL, informando data e seção
     -> devolve um arquivo .zip contendo um .xml por matéria publicada
     naquela seção, naquele dia.
  3) Cada .xml é lido e filtrado pelas DOU_KEYWORDS (mesma lógica de
     antes: contém, case-insensitive, sem acento).

IMPORTANTE — sobre a estabilidade da estrutura do XML:
O INLABS não tem uma documentação pública e versionada do schema exato de
cada tag/atributo do XML. Este código usa múltiplos nomes alternativos
por campo (mesmo princípio da versão anterior) para resistir a pequenas
variações. Se a Imprensa Nacional mudar a estrutura de forma mais
profunda, os nomes em `_ATTR_*` abaixo podem precisar de ajuste.
"""
from __future__ import annotations

import io
import logging
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
from xml.etree import ElementTree

import holidays
import requests

logger = logging.getLogger(__name__)

INLABS_LOGIN_URL = "https://inlabs.in.gov.br/logaudio.php"
INLABS_DOWNLOAD_URL = "https://inlabs.in.gov.br/index.php"
INLABS_LEITURA_URL = "https://www.in.gov.br/leiturajornal"

USER_AGENT = (
    "MonitoramentoDOU-MDIC/1.0 "
    "(automacao interna de clipping do DOU via INLABS; 1 consulta/dia)"
)

BR_HOLIDAYS = holidays.Brazil()

# Nomes alternativos de atributos, pois o INLABS não documenta um schema
# fixo/versionado publicamente.
_ATTR_TITULO = ("name", "title", "titulo", "ementa")
_ATTR_ORGAO = ("artCategory", "pubName", "hierarchyStr", "orgao", "displayName")
_ATTR_TIPO = ("artType", "tipo", "identifica")
_ATTR_NUMERO = ("numberDocument", "artNumber", "numero")
_ATTR_ID = ("id", "idMateria", "identifica")


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
    """
    Retorna a data que deve ser consultada no DOU: o dia corrente, ou o
    último dia útil anterior se cair em fim de semana/feriado nacional.
    """
    ref = today or date.today()
    while ref.weekday() >= 5 or ref in BR_HOLIDAYS:  # 5 = sábado, 6 = domingo
        ref -= timedelta(days=1)
    return ref


def _login(session: requests.Session, email: str, password: str, timeout: int) -> None:
    if not email or not password:
        raise InlabsAuthError(
            "INLABS_EMAIL/INLABS_SENHA não configurados (verifique os GitHub Secrets)."
        )
    resp = session.post(
        INLABS_LOGIN_URL,
        data={"email": email, "password": password},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    # O INLABS não usa códigos HTTP de erro padronizados para login inválido
    # em todos os casos, então checamos também se algum cookie de sessão foi
    # de fato recebido.
    if resp.status_code >= 400 or not session.cookies:
        raise InlabsAuthError(
            f"Falha ao autenticar no INLABS (status {resp.status_code}). "
            "Confira o e-mail/senha configurados nos GitHub Secrets "
            "INLABS_EMAIL e INLABS_SENHA."
        )


def _download_zip(
    session: requests.Session, reference_date: date, secao: str, timeout: int
) -> bytes:
    params = {"p": reference_date.strftime("%d-%m-%Y"), "dl": secao.upper()}
    resp = session.get(
        INLABS_DOWNLOAD_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if "zip" not in content_type and resp.content[:2] != b"PK":
        # Não veio um .zip de verdade — provavelmente não há edição para
        # essa data/seção (ex.: feriado não previsto na lib `holidays`,
        # ou edição extra ainda não publicada).
        raise DouUnavailableError(
            f"O INLABS não retornou um arquivo .zip para {params['p']} "
            f"(seção {params['dl']}). Pode não haver edição nessa data."
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


def _normalize(xml_bytes: bytes, reference_date: date) -> Optional[Publicacao]:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        logger.warning("Um dos arquivos XML do INLABS não pôde ser lido (ignorado).")
        return None

    # O elemento raiz normalmente já é o próprio <article>; se não for,
    # procuramos a primeira ocorrência dentro da árvore.
    article = root if root.tag.lower().endswith("article") else root.find(".//article")
    if article is None:
        article = root

    titulo = _first_present(article, *_ATTR_TITULO)
    orgao = _first_present(article, *_ATTR_ORGAO)
    tipo_ato = _first_present(article, *_ATTR_TIPO)
    numero_ato = _first_present(article, *_ATTR_NUMERO, default="s/nº")
    art_id = _first_present(article, *_ATTR_ID)

    corpo_texto = _extract_text(article)
    if not titulo:
        # Se não achamos um título nos atributos, usamos o começo do texto.
        titulo = corpo_texto[:200] if corpo_texto else "(sem título)"

    link = (
        f"https://www.in.gov.br/web/dou/-/{art_id}"
        if art_id
        else f"{INLABS_LEITURA_URL}?data={reference_date.strftime('%d-%m-%Y')}&secao=do2"
    )

    return Publicacao(
        data_publicacao=reference_date.strftime("%d/%m/%Y"),
        orgao=orgao or "Não identificado",
        titulo=titulo,
        tipo_ato=tipo_ato or "-",
        numero_ato=numero_ato,
        link=link,
        raw={"xml_len": len(xml_bytes), "texto": corpo_texto[:2000]},
    )


def _matches_keywords(pub: Publicacao, keywords: list) -> bool:
    haystack = _strip_accents(
        f"{pub.titulo} {pub.orgao} {pub.raw.get('texto', '')}"
    ).lower()
    return any(_strip_accents(kw).lower() in haystack for kw in keywords)


def search_dou(
    keywords: list,
    secao: str = "do2",
    reference_date: Optional[date] = None,
    max_retries: int = 3,
    timeout: int = 30,
    inlabs_email: str = "",
    inlabs_password: str = "",
):
    """
    Ponto de entrada principal do módulo (agora via INLABS).

    Retorna (data_efetivamente_consultada, lista_de_Publicacao) já
    filtrada pelas `keywords`. Levanta DouUnavailableError (ou a
    subclasse InlabsAuthError) se não for possível concluir a consulta.
    """
    ref_date = reference_date or get_reference_date()

    last_error: Optional[Exception] = None
    zip_bytes: Optional[bytes] = None
    for attempt in range(1, max_retries + 1):
        try:
            session = requests.Session()
            _login(session, inlabs_email, inlabs_password, timeout)
            zip_bytes = _download_zip(session, ref_date, secao, timeout)
            break
        except InlabsAuthError:
            # Credenciais erradas não se resolvem tentando de novo.
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
            pub = _normalize(zf.read(name), ref_date)
            if pub is not None:
                all_pubs.append(pub)

    filtered = [pub for pub in all_pubs if _matches_keywords(pub, keywords)]

    logger.info(
        "DOU %s (INLABS): %s publicações na seção '%s', %s após filtro de palavras-chave.",
        ref_date, len(all_pubs), secao, len(filtered),
    )
    return ref_date, filtered
