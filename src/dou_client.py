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
  3) Cada .xml é lido e filtrado por ORG_KEYWORDS (ver abaixo).

CORREÇÃO IMPORTANTE (05/07/2026) — filtro estava errado:
A versão anterior buscava as keywords dentro de TÍTULO + ÓRGÃO + TEXTO
COMPLETO do artigo. Isso trazia publicações de QUALQUER ministério que
apenas MENCIONASSE "MDIC" ou similar no corpo (ex.: cessão de servidor,
portarias de pessoal de outros órgãos que citam o MDIC de passagem).

O comportamento correto — o mesmo que o filtro oficial do site faz com
os parâmetros `org` (unidade principal) e `org_sub` (unidade subordinada)
em https://www.in.gov.br/leiturajornal — é filtrar apenas pelo ÓRGÃO
PUBLICADOR (quem efetivamente publicou o ato), não pelo conteúdo do
texto. Por isso `_matches_keywords` agora olha só `pub.orgao`.

IMPORTANTE — sobre a estabilidade da estrutura do XML:
O INLABS não tem uma documentação pública e versionada do schema exato de
cada tag/atributo do XML. Este código usa múltiplos nomes alternativos
por campo (mesmo princípio da versão anterior) para resistir a pequenas
variações. Se a Imprensa Nacional mudar a estrutura de forma mais
profunda, os nomes em `_ATTR_*` abaixo podem precisar de ajuste.

SOBRE O LINK "ABRIR NO DOU" (ver DEBUG_XML_ATTRS abaixo):
Os links reais do site têm o formato
`https://www.in.gov.br/web/dou/-/<slug-do-titulo>-<numero>`, não apenas
um ID numérico. Não temos confirmação de qual atributo do XML do INLABS
carrega esse slug completo (a Imprensa Nacional não documenta isso
publicamente). Enquanto isso não for confirmado, o link direto pode não
abrir corretamente — por segurança, quando não temos certeza, geramos um
link de BUSCA (que sempre funciona) em vez de arriscar um link quebrado.
Ative DOU_DEBUG_XML_ATTRS=true para logar os atributos brutos do XML e
descobrir o nome certo do campo; assim que confirmado, é só adicionar
esse nome em `_ATTR_ID` ou `_ATTR_SLUG` abaixo.
"""
from __future__ import annotations

import io
import logging
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
from urllib.parse import quote
from xml.etree import ElementTree

import holidays
import requests

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

# Nomes alternativos de atributos, pois o INLABS não documenta um schema
# fixo/versionado publicamente.
_ATTR_TITULO = ("name", "title", "titulo", "ementa")
_ATTR_ORGAO = ("artCategory", "pubName", "hierarchyStr", "orgao", "displayName")
_ATTR_TIPO = ("artType", "tipo", "identifica")
_ATTR_NUMERO = ("numberDocument", "artNumber", "numero")
_ATTR_ID = ("id", "idMateria", "identifica")
# Possíveis nomes de um "slug" completo (título amigável usado na URL
# pública). Ainda não confirmados contra um XML real — ver DEBUG acima.
_ATTR_SLUG = ("urlTitle", "friendlyUrl", "slug", "idOficial", "pdfPage")

# Nomes oficiais completos usados no filtro por órgão (mesmos nomes do
# link de busca oficial do site, para bater exatamente com "MDIC" como
# unidade principal e "Inmetro" como unidade subordinada).
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
    """
    Retorna a data que deve ser consultada no DOU: o dia corrente, ou o
    último dia útil anterior se cair em fim de semana/feriado nacional.
    """
    ref = today or date.today()
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
        # Padrão oficial do INLABS para "não há edição publicada nessa
        # data/seção" (ex.: feriado, ou edição ainda não publicada).
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
    """Link de BUSCA (não o link direto do artigo) já filtrado pelos
    parâmetros oficiais de órgão/unidade subordinada, no mesmo formato do
    link que abre a edição do dia com MDIC + Inmetro pré-selecionados.
    Esse link sempre abre (é uma tela de busca do site oficial), diferente
    de um link direto por ID que pode estar errado."""
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

    # O elemento raiz normalmente já é o próprio <article>; se não for,
    # procuramos a primeira ocorrência dentro da árvore.
    article = root if root.tag.lower().endswith("article") else root.find(".//article")
    if article is None:
        article = root

    if debug_attrs:
        # Ativado via DOU_DEBUG_XML_ATTRS=true (ver config.py). Loga os
        # atributos crus do XML para identificarmos, com dado real, qual
        # campo carrega o slug/URL amigável do artigo (ver nota no topo
        # do arquivo sobre o link "Abrir no DOU").
        logger.info("DEBUG atributos do <article>: %s", dict(article.attrib))

    titulo = _first_present(article, *_ATTR_TITULO)
    orgao = _first_present(article, *_ATTR_ORGAO)
    tipo_ato = _first_present(article, *_ATTR_TIPO)
    numero_ato = _first_present(article, *_ATTR_NUMERO, default="s/nº")
    art_id = _first_present(article, *_ATTR_ID)
    slug = _first_present(article, *_ATTR_SLUG)

    corpo_texto = _extract_text(article)
    if not titulo:
        # Se não achamos um título nos atributos, usamos o começo do texto.
        titulo = corpo_texto[:200] if corpo_texto else "(sem título)"

    if slug:
        # Só usamos link direto se tivermos um slug (nome amigável) —
        # nunca um ID numérico puro, que não corresponde ao formato real
        # das URLs do site (ex.: /web/dou/-/portaria-n-296-24096588).
        link = f"https://www.in.gov.br/web/dou/-/{slug}"
    else:
        # Sem confirmação do campo certo, usamos o link de busca (que
        # sempre abre) em vez de arriscar um link quebrado.
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
    """
    Ponto de entrada principal do módulo (agora via INLABS).

    `keywords` aqui são tratadas como nomes/siglas do ÓRGÃO PUBLICADOR
    (ex.: "MDIC", "Inmetro"), e o filtro é aplicado apenas sobre o campo
    de órgão de cada publicação — não sobre o texto completo do artigo.

    Retorna (data_efetivamente_consultada, lista_de_Publicacao) já
    filtrada. Levanta DouUnavailableError (ou a subclasse
    InlabsAuthError) se não for possível concluir a consulta.
    """
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
            pub = _normalize(zf.read(name), ref_date, secao, debug_attrs=debug_xml_attrs)
            if pub is not None:
                all_pubs.append(pub)

    filtered = [pub for pub in all_pubs if _matches_keywords(pub, keywords)]

    logger.info(
        "DOU %s (INLABS): %s publicações na seção '%s', %s após filtro de órgão (MDIC/Inmetro).",
        ref_date, len(all_pubs), secao, len(filtered),
    )
    return ref_date, filtered
