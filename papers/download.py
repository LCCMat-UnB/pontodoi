"""papers/download.py — orquestração do download em camadas.

Mesma prioridade ética do baixar_papers_por_doi.py original:
  1) Unpaywall (acesso aberto legal)
  2) Acesso institucional automático (Playwright, perfil autenticado)
  3) Modo assistido (você mesmo baixa, no navegador padrão)

Opera sobre uma Sessao: só processa itens 'pendente', atualiza o status de
cada um ('baixado' / 'nao_resolvido') e salva o progresso a cada item —
então dá para interromper e retomar com `pontodoi continuar <id>`.
"""

from __future__ import annotations

import time
from contextlib import nullcontext
from pathlib import Path
from typing import Callable

import requests

from . import ui
from .config import Config
from .sessions import Sessao

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"


def consultar_unpaywall(doi: str, email: str) -> dict | None:
    try:
        r = requests.get(f"{UNPAYWALL_BASE}/{doi}", params={"email": email}, timeout=15)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException:
        pass
    return None


def extrair_link_pdf_oa(dados: dict) -> str | None:
    best = dados.get("best_oa_location")
    if best and best.get("url_for_pdf"):
        return best["url_for_pdf"]
    if best and best.get("url"):
        return best["url"]
    return None


def baixar_arquivo(url: str, destino: Path, session: requests.Session) -> bool:
    try:
        r = session.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and (
            r.headers.get("content-type", "").lower().count("pdf") or r.content[:4] == b"%PDF"
        ):
            destino.write_bytes(r.content)
            return True
    except requests.RequestException:
        pass
    return False


def nome_arquivo(doi: str) -> str:
    return doi.replace("/", "_") + ".pdf"


def executar(
    sessao: Sessao,
    config: Config,
    modo: str = "auto",  # "auto" | "assistido"
    usar_institucional: bool = True,
    ao_resolver_item: Callable[[dict, bool], None] | None = None,
) -> dict[str, int]:
    """Processa os itens pendentes da sessão. Retorna contagem final por status.

    modo="assistido": quando o institucional automático falhar num DOI, abre
    o navegador padrão para download manual. modo="auto": DOIs que falharem
    vão direto para 'nao_resolvido', sem interromper o lote.

    ao_resolver_item(item, resolvido): callback opcional chamado logo após
    CADA item ser decidido (baixado ou não_resolvido) — ANTES de seguir para
    o próximo. Existe para permitir refletir o resultado em sistemas externos
    (ex: o registry.jsonl compartilhado com SPE/parsing-papers) item a item,
    em vez de só no final do lote inteiro: um lote de dezenas de DOIs pode
    levar minutos, e se o processo for interrompido no meio (Ctrl+C, queda de
    rede, fechamento do terminal), os itens já baixados não devem ficar
    "invisíveis" para quem só olha o registry depois.
    """
    from .institucional import AcessoInstitucional
    from .config import Config as _C  # noqa: F401 (só p/ clareza de tipo)

    pendentes = sessao.pendentes()
    if not pendentes:
        ui.aviso("Nada pendente nesta sessão — todos os itens já foram processados.")
        return sessao.resumo()

    session = requests.Session()
    email_unpaywall = config.unpaywall()
    pasta_perfil = config.dir_workspace() / "perfil_navegador_institucional"

    habilitar_assistido = modo == "assistido"

    gerenciador = (
        AcessoInstitucional(pasta_perfil)
        if usar_institucional and pasta_perfil.exists()
        else nullcontext(None)
    )
    if usar_institucional and not pasta_perfil.exists():
        ui.aviso("Perfil institucional não configurado — pulando a camada institucional.")
        ui.dica("Rode o login primeiro (menu → Login institucional, ou `pontodoi login`).")

    with gerenciador as acesso, ui.barra_download(len(pendentes)) as (progresso, tarefa):
        for it in pendentes:
            doi = it["doi"]
            destino = sessao.pasta_pdfs / nome_arquivo(doi)
            progresso.update(tarefa, description=f"[primaria]{doi}[/]")

            if destino.exists():
                sessao.marcar(doi, "baixado")
                sessao.salvar()
                if ao_resolver_item:
                    ao_resolver_item(it, True)
                progresso.advance(tarefa)
                continue

            resolvido = _processar_um(
                doi, destino, session, email_unpaywall, acesso, habilitar_assistido, progresso
            )
            # modo assistido pode ter sido desligado pelo usuário ('sair')
            if resolvido == "sair":
                habilitar_assistido = False
                resolvido = False

            sessao.marcar(doi, "baixado" if resolvido else "nao_resolvido")
            sessao.salvar()
            if ao_resolver_item:
                ao_resolver_item(it, bool(resolvido))
            progresso.advance(tarefa)
            time.sleep(config.intervalo_seg)

    caminho_nao = sessao.exportar_nao_resolvidos()
    if caminho_nao:
        ui.aviso(f"DOIs não resolvidos listados em: {caminho_nao}")
        ui.dica("Esses você pode pedir via COMUT / empréstimo entre bibliotecas.")
    return sessao.resumo()


def _processar_um(doi, destino, session, email_unpaywall, acesso, habilitar_assistido, progresso=None):
    """Aplica as camadas a um único DOI. Retorna True/False ou 'sair'."""
    # Camada 1: Unpaywall
    if email_unpaywall:
        dados = consultar_unpaywall(doi, email_unpaywall)
        link = extrair_link_pdf_oa(dados) if dados else None
        if link and baixar_arquivo(link, destino, session):
            return True

    # Camada 2 (API de TDM da editora) — ponto de extensão futuro.

    # Camada 3: institucional automático (+ assistido opcional)
    if acesso and getattr(acesso, "disponivel", False):
        sucesso, pagina = acesso.tentar_automatico(doi, destino)
        if sucesso:
            return True
        if habilitar_assistido:
            resultado = acesso.modo_assistido(doi, destino, pagina, progresso=progresso)
            if resultado == "baixado":
                return True
            if resultado == "sair":
                return "sair"
        elif pagina is not None:
            try:
                pagina.close()
            except Exception:
                pass
    return False
