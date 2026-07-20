"""papers/sessions.py — sessões retomáveis.

Cada busca por um(a) pesquisador(a) vira uma sessão persistente em disco:

  <workspace>/sessoes/<id>/
      sessao.json          -> metadados + lista de itens com status
      dois.txt             -> um DOI por linha (compat. com scripts antigos)
      dois_detalhado.csv   -> título/ano/fonte/DOI
      papers_baixados/     -> PDFs
      nao_resolvidos.csv   -> DOIs para COMUT/EEB

Status por item: "pendente" | "baixado" | "nao_resolvido".
Assim, `pontodoi continuar <id>` só processa o que ainda está "pendente".
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from .config import Config


def _slug(texto: str) -> str:
    texto = (texto or "sessao").strip().lower()
    texto = re.sub(r"[^\w\s-]", "", texto, flags=re.UNICODE)
    texto = re.sub(r"[\s_-]+", "-", texto).strip("-")
    return texto[:40] or "sessao"


class Sessao:
    def __init__(self, dados: dict, pasta: Path):
        self.dados = dados
        self.pasta = pasta

    # --- identidade / metadados -------------------------------------------
    @property
    def id(self) -> str:
        return self.dados["id"]

    @property
    def itens(self) -> list[dict]:
        return self.dados.setdefault("itens", [])

    @property
    def pasta_pdfs(self) -> Path:
        p = self.pasta / "papers_baixados"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # --- criação ----------------------------------------------------------
    @classmethod
    def criar(
        cls,
        config: Config,
        nome_autor: str,
        orcid: str | None = None,
        author_id: str | None = None,
        de: int | None = None,
        ate: int | None = None,
    ) -> "Sessao":
        agora = datetime.now()
        sid = f"{agora:%Y-%m-%d_%H%M}_{_slug(nome_autor)}"
        pasta = _dir_sessoes(config) / sid
        pasta.mkdir(parents=True, exist_ok=True)
        dados = {
            "id": sid,
            "criada_em": agora.isoformat(timespec="seconds"),
            "atualizada_em": agora.isoformat(timespec="seconds"),
            "autor": {"nome": nome_autor, "openalex_id": author_id},
            "orcid": orcid,
            "periodo": {"de": de, "ate": ate},
            "itens": [],
        }
        sessao = cls(dados, pasta)
        sessao.salvar()
        return sessao

    # --- itens ------------------------------------------------------------
    def definir_itens(self, itens: list[dict]) -> None:
        """Popula a sessão com os itens descobertos (todos 'pendente')."""
        self.dados["itens"] = [
            {
                "doi": it["doi"],
                "titulo": it.get("titulo") or "sem título",
                "ano": it.get("ano"),
                "fonte": it.get("fonte"),
                "status": it.get("status", "pendente"),
            }
            for it in itens
        ]
        self._exportar_planilhas()
        self.salvar()

    def pendentes(self) -> list[dict]:
        return [it for it in self.itens if it.get("status") == "pendente"]

    def marcar(self, doi: str, status: str) -> None:
        for it in self.itens:
            if it["doi"] == doi:
                it["status"] = status
                break

    def resumo(self) -> dict[str, int]:
        contagem = {"pendente": 0, "baixado": 0, "nao_resolvido": 0}
        for it in self.itens:
            contagem[it.get("status", "pendente")] = contagem.get(it.get("status", "pendente"), 0) + 1
        return contagem

    # --- persistência -----------------------------------------------------
    def salvar(self) -> None:
        self.dados["atualizada_em"] = datetime.now().isoformat(timespec="seconds")
        (self.pasta / "sessao.json").write_text(
            json.dumps(self.dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _exportar_planilhas(self) -> None:
        """Gera dois.txt e dois_detalhado.csv (compat. com o fluxo antigo)."""
        (self.pasta / "dois.txt").write_text(
            "\n".join(it["doi"] for it in self.itens) + "\n", encoding="utf-8"
        )
        with open(self.pasta / "dois_detalhado.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["doi", "ano", "titulo", "fonte", "status"])
            w.writeheader()
            for it in sorted(self.itens, key=lambda x: (x.get("ano") or 0)):
                w.writerow({k: it.get(k) for k in ["doi", "ano", "titulo", "fonte", "status"]})

    def exportar_nao_resolvidos(self) -> Path | None:
        nao = [it for it in self.itens if it.get("status") == "nao_resolvido"]
        if not nao:
            return None
        caminho = self.pasta / "nao_resolvidos.csv"
        with open(caminho, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["doi", "link_direto"])
            for it in nao:
                w.writerow([it["doi"], f"https://doi.org/{it['doi']}"])
        return caminho


def _dir_sessoes(config: Config) -> Path:
    p = config.dir_workspace() / "sessoes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def carregar(config: Config, sid: str) -> Sessao | None:
    pasta = _dir_sessoes(config) / sid
    arquivo = pasta / "sessao.json"
    if not arquivo.exists():
        return None
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    return Sessao(dados, pasta)


def listar(config: Config) -> list[Sessao]:
    """Sessões existentes, da mais recente para a mais antiga."""
    base = _dir_sessoes(config)
    sessoes = []
    for arquivo in base.glob("*/sessao.json"):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            sessoes.append(Sessao(dados, arquivo.parent))
        except (json.JSONDecodeError, OSError):
            continue
    sessoes.sort(key=lambda s: s.dados.get("criada_em", ""), reverse=True)
    return sessoes
