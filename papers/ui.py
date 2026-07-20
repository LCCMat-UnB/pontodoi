"""papers/ui.py — camada de apresentação (cores, banner, tabelas, prompts).

Tudo que é "como aparece na tela" mora aqui, para o resto do código não
precisar saber de Rich. Se um dia virar web app, só esta camada é trocada.

Paleta (tema Rich nomeado, para consistência em toda a CLI):
  primaria  -> ciano  (títulos, destaques de ação)
  ok        -> verde  (sucesso, baixado)
  aviso     -> amarelo (assistido, atenção)
  erro      -> vermelho (falha, não resolvido)
  info      -> azul   (metadados, dicas)
  suave     -> cinza  (texto secundário)
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

TEMA = Theme(
    {
        "primaria": "bold cyan",
        "ok": "bold green",
        "aviso": "bold yellow",
        "erro": "bold red",
        "info": "blue",
        "suave": "grey62",
        "titulo": "bold white on cyan",
        "doi": "magenta",
    }
)

console = Console(theme=TEMA)

# Ícones/afixos de status usados em listagens de sessão.
STATUS_ICONE = {
    "pendente": ("[suave]○[/]", "pendente"),
    "baixado": ("[ok]●[/]", "baixado"),
    "nao_resolvido": ("[erro]✗[/]", "não resolvido"),
}


LETREIRO = r"""
                                █████                    █████           ███
                               ░░███                    ░░███           ░░░
 ████████   ██████  ████████   ███████    ██████      ███████   ██████  ████
░░███░░███ ███░░███░░███░░███ ░░░███░    ███░░███    ███░░███  ███░░███░░███
 ░███ ░███░███ ░███ ░███ ░███   ░███    ░███ ░███   ░███ ░███ ░███ ░███ ░███
 ░███ ░███░███ ░███ ░███ ░███   ░███ ███░███ ░███   ░███ ░███ ░███ ░███ ░███
 ░███████ ░░██████  ████ █████  ░░█████ ░░██████  ██░░████████░░██████  █████
 ░███░░░   ░░░░░░  ░░░░ ░░░░░    ░░░░░   ░░░░░░  ░░  ░░░░░░░░  ░░░░░░  ░░░░░
 ░███
 █████
░░░░░
"""


def banner() -> None:
    """Letreiro colorido mostrado ao abrir a CLI."""
    console.print(Text(LETREIRO.strip("\n"), style="primaria"), highlight=False)
    console.print(
        Text(
            "\nrecuperação de papers · Unpaywall + CAFe/CAPES + modo assistido",
            style="suave",
        ),
        highlight=False,
    )

def top() -> None:
    console.rule(f"", style="cyan")

def secao(texto: str) -> None:
    console.rule(f"[primaria]{texto}[/]", style="cyan")


def ok(msg: str) -> None:
    console.print(f"[ok]✓[/] {msg}")


def aviso(msg: str) -> None:
    console.print(f"[aviso]![/] {msg}")


def erro(msg: str) -> None:
    console.print(f"[erro]✗[/] {msg}")


def info(msg: str) -> None:
    console.print(f"[info]i[/] {msg}")


def dica(msg: str) -> None:
    console.print(f"  [suave]{msg}[/]")


# ---------------------------------------------------------------- prompts ---

def perguntar(msg: str, padrao: str | None = None) -> str:
    return Prompt.ask(
        f"[primaria]{msg}[/]",
        default=padrao or "",
        show_default=bool(padrao),
        console=console,
    ).strip()


def _limpar(texto: str) -> str:
    # Remove BOM (alguns terminais/pipes no Windows prefixam ﻿) e espaços.
    return texto.lstrip("﻿").strip()


def perguntar_int(msg: str, padrao: int | None = None) -> int | None:
    resp = _limpar(
        Prompt.ask(f"[primaria]{msg}[/]", default="", show_default=False, console=console)
    )
    if not resp:
        return padrao
    try:
        return int(resp)
    except ValueError:
        erro("valor inválido, ignorando.")
        return padrao


def confirmar(msg: str, padrao: bool = True) -> bool:
    return Confirm.ask(f"[primaria]{msg}[/]", default=padrao, console=console)


def escolher_opcao(msg: str, minimo: int, maximo: int) -> int:
    # Implementado à mão (em vez de IntPrompt) para tolerar BOM/espaços que
    # alguns terminais e pipes do Windows prefixam ao stdin.
    while True:
        resp = _limpar(
            Prompt.ask(f"[primaria]{msg}[/]", default="", show_default=False, console=console)
        )
        if resp.isdigit() and minimo <= int(resp) <= maximo:
            return int(resp)
        erro(f"digite um número entre {minimo} e {maximo}.")


# ---------------------------------------------------------------- tabelas ---

def tabela_candidatos(candidatos: list[dict]) -> None:
    """Mostra os autores homônimos do OpenAlex para o usuário desambiguar."""
    tab = Table(title="Autores encontrados", border_style="cyan", header_style="primaria")
    tab.add_column("#", justify="right", style="aviso")
    tab.add_column("Nome", style="white")
    tab.add_column("Instituição mais recente", style="info")
    tab.add_column("Trabalhos", justify="right", style="suave")
    tab.add_column("ORCID", style="doi")

    for i, autor in enumerate(candidatos, 1):
        instituicoes = autor.get("last_known_institutions") or []
        instituicao = instituicoes[0].get("display_name") if instituicoes else "—"
        orcid = (autor.get("orcid") or "—").replace("https://orcid.org/", "")
        tab.add_row(
            str(i),
            autor.get("display_name", "—"),
            instituicao or "—",
            str(autor.get("works_count", 0)),
            orcid,
        )
    console.print(tab)


def tabela_sessoes(sessoes: list[dict]) -> None:
    tab = Table(title="Sessões", border_style="cyan", header_style="primaria")
    tab.add_column("#", justify="right", style="aviso")
    tab.add_column("Autor", style="white")
    tab.add_column("Período", style="info")
    tab.add_column("DOIs", justify="right")
    tab.add_column("Baixados", justify="right", style="ok")
    tab.add_column("Pendentes", justify="right", style="suave")
    tab.add_column("Criada em", style="suave")

    for i, s in enumerate(sessoes, 1):
        itens = s.get("itens", [])
        baixados = sum(1 for it in itens if it.get("status") == "baixado")
        pendentes = sum(1 for it in itens if it.get("status") == "pendente")
        periodo = s.get("periodo") or {}
        de, ate = periodo.get("de"), periodo.get("ate")
        faixa = f"{de or '…'}–{ate or '…'}" if (de or ate) else "todos"
        tab.add_row(
            str(i),
            (s.get("autor") or {}).get("nome", "—"),
            faixa,
            str(len(itens)),
            str(baixados),
            str(pendentes),
            (s.get("criada_em") or "")[:16].replace("T", " "),
        )
    console.print(tab)


def tabela_itens(itens: Iterable[dict], limite: int = 20) -> None:
    tab = Table(border_style="cyan", header_style="primaria")
    tab.add_column("Status", justify="center")
    tab.add_column("Ano", justify="right", style="info")
    tab.add_column("DOI", style="doi")
    tab.add_column("Título", style="white")

    itens = list(itens)
    for it in itens[:limite]:
        icone, _ = STATUS_ICONE.get(it.get("status", "pendente"), ("?", "?"))
        titulo = (it.get("titulo") or "sem título")
        if len(titulo) > 70:
            titulo = titulo[:67] + "…"
        tab.add_row(icone, str(it.get("ano") or "—"), it.get("doi", "—"), titulo)
    console.print(tab)
    if len(itens) > limite:
        dica(f"... e mais {len(itens) - limite} item(ns).")


# ---------------------------------------------------------------- progresso ---

@contextmanager
def barra_download(total: int):
    """Context manager de barra de progresso para o lote de downloads."""
    progresso = Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[primaria]baixando[/]"),
        BarColumn(complete_style="green", finished_style="green"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )
    with progresso:
        tarefa = progresso.add_task("download", total=total)
        yield progresso, tarefa
