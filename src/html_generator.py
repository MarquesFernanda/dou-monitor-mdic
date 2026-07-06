from __future__ import annotations

import html
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Union

from .dou_client import Publicacao

logger = logging.getLogger(__name__)

MAX_HISTORICO = 30  # quantos dias mostrar na lista de histórico da página


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _load_historico(historico_path: Path) -> list:
    if not historico_path.exists():
        return []
    try:
        return json.loads(historico_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Não foi possível ler %s, começando histórico do zero.", historico_path)
        return []


def _save_historico(historico_path: Path, historico: list) -> None:
    historico_path.write_text(
        json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_publicacoes_html(publicacoes: List[Publicacao]) -> str:
    if not publicacoes:
        return '<p class="vazio">Nenhuma publicação encontrada nesta data.</p>'

    linhas = []
    for pub in publicacoes:
        linhas.append(
            "<tr>"
            f"<td>{_esc(pub.data_publicacao)}</td>"
            f"<td>{_esc(pub.orgao)}</td>"
            f"<td>{_esc(pub.titulo)}</td>"
            f"<td>{_esc(pub.numero_ato)}</td>"
            f'<td><a href="{_esc(pub.link)}" target="_blank" rel="noopener">Abrir no DOU</a></td>'
            "</tr>"
        )
    return (
        '<table class="pub-table">'
        "<thead><tr><th>Data</th><th>Órgão</th><th>Título/Assunto</th>"
        "<th>Nº do Ato</th><th>Link</th></tr></thead>"
        f"<tbody>{''.join(linhas)}</tbody>"
        "</table>"
    )


def _build_historico_html(historico: list) -> str:
    if not historico:
        return ""
    itens = []
    for entry in historico[:MAX_HISTORICO]:
        qtd = entry.get("quantidade", 0)
        data_str = entry.get("data", "")
        docx_link = entry.get("docx_link")
        qtd_texto = f"{qtd} publicação(ões)" if qtd else "nenhuma publicação"
        link_html = (
            f' — <a href="{_esc(docx_link)}" target="_blank" rel="noopener">relatório .docx</a>'
            if docx_link
            else ""
        )
        itens.append(f"<li><strong>{_esc(data_str)}</strong>: {qtd_texto}{link_html}</li>")
    return (
        "<h2>Histórico recente</h2>"
        f"<ul class=\"historico\">{''.join(itens)}</ul>"
    )


def generate_error_page(
    error_message: str,
    docs_dir: Union[str, Path] = "docs",
) -> Path:
    """Gera uma página avisando que a checagem de hoje falhou, em vez de
    deixar a página anterior (ou nenhuma página) sem explicação. Usada
    quando o DOU está indisponível/bloqueando acesso automatizado."""
    docs_dir = Path(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)

    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")

    pagina = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monitoramento Diário DOU - MDIC/Inmetro</title>
<meta http-equiv="refresh" content="1800">
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0;
         padding: 24px; background: #f4f6f8; color: #1f2933; }}
  .container {{ max-width: 720px; margin: 40px auto; background: #fff;
                border-radius: 8px; padding: 24px 32px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  h1 {{ color: #b71c1c; font-size: 1.3rem; }}
  footer {{ margin-top: 24px; font-size: .78rem; color: #9aa5b1; }}
</style>
</head>
<body>
  <div class="container">
    <h1>⚠️ Não foi possível verificar o DOU hoje</h1>
    <p>A automação tentou consultar o Diário Oficial da União em {_esc(agora)}
    e não conseguiu. Verifique manualmente em
    <a href="https://www.in.gov.br/leiturajornal" target="_blank" rel="noopener">in.gov.br/leiturajornal</a>.</p>
    <p><em>{_esc(error_message)}</em></p>
    <footer>A próxima tentativa automática ocorre amanhã às 8h (Brasília).</footer>
  </div>
</body>
</html>
"""
    index_path = docs_dir / "index.html"
    index_path.write_text(pagina, encoding="utf-8")
    logger.info("Página de erro gerada em %s", index_path)
    return index_path


def generate_html_page(
    publicacoes: List[Publicacao],
    reference_date: date,
    docs_dir: Union[str, Path] = "docs",
    docx_link: Optional[str] = None,
) -> Path:
    """Gera docs/index.html e atualiza docs/historico.json.

    Retorna o Path do index.html gerado.
    """
    docs_dir = Path(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)

    historico_path = docs_dir / "historico.json"
    historico = _load_historico(historico_path)

    data_iso = reference_date.isoformat()
    data_str = reference_date.strftime("%d/%m/%Y")

    # Remove uma entrada antiga da mesma data (caso a Action rode 2x no
    # mesmo dia, ex.: manual + agendada) e insere a atual no topo.
    historico = [e for e in historico if e.get("data_iso") != data_iso]
    historico.insert(
        0,
        {
            "data_iso": data_iso,
            "data": data_str,
            "quantidade": len(publicacoes),
            "docx_link": docx_link,
        },
    )
    historico = historico[:MAX_HISTORICO]
    _save_historico(historico_path, historico)

    atualizado_em = datetime.now().strftime("%d/%m/%Y às %H:%M")

    pagina = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monitoramento Diário DOU - MDIC/Inmetro</title>
<meta http-equiv="refresh" content="1800">
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0;
         padding: 24px; background: #f4f6f8; color: #1f2933; }}
  .container {{ max-width: 960px; margin: 0 auto; background: #fff;
                border-radius: 8px; padding: 24px 32px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  h1 {{ color: #1f4e79; font-size: 1.5rem; margin-bottom: 4px; }}
  .subtitulo {{ color: #52606d; margin-top: 0; margin-bottom: 24px; }}
  .pub-table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: .92rem; }}
  .pub-table th {{ background: #1f4e79; color: #fff; text-align: left; padding: 8px 10px; }}
  .pub-table td {{ padding: 8px 10px; border-bottom: 1px solid #e4e7eb; vertical-align: top; }}
  .pub-table tr:nth-child(even) {{ background: #f8f9fa; }}
  .vazio {{ color: #52606d; font-style: italic; }}
  .historico {{ font-size: .88rem; color: #334; padding-left: 20px; }}
  .historico li {{ margin-bottom: 4px; }}
  footer {{ margin-top: 32px; font-size: .78rem; color: #9aa5b1; }}
  a {{ color: #0563c1; }}
</style>
</head>
<body>
  <div class="container">
    <h1> Monitoramento Diário DOU — MDIC/Inmetro</h1>
    <p class="subtitulo">Edição de {_esc(data_str)} · Seção 2 · atualizado em {_esc(atualizado_em)}</p>

    {_build_publicacoes_html(publicacoes)}

    {'<p><a href="' + _esc(docx_link) + '" target="_blank" rel="noopener"> Baixar relatório completo em Word</a></p>' if docx_link else ''}

    {_build_historico_html(historico)}

    <footer>Página gerada automaticamente pela automação de monitoramento do DOU. Atualiza todos os dias por volta das 8h (Brasília).</footer>
  </div>
</body>
</html>
"""

    index_path = docs_dir / "index.html"
    index_path.write_text(pagina, encoding="utf-8")
    logger.info("Página HTML gerada em %s", index_path)
    return index_path
