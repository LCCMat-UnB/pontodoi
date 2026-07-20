"""papers/registry.py — leitura/escrita do registro compartilhado (registry.jsonl).

Ponto de handoff entre SPE (busca + PRISMA), pontodoi (este projeto — download
de PDF) e parsing-papers (extração de métricas). Ver INTEGRATION.md e
registry.schema.json no repo do synoptic-paper-engine para o contrato
completo.

Este módulo é deliberadamente autocontido (só stdlib): a mesma lógica de
~100 linhas é reimplementada, não importada, em cada um dos três projetos —
"contrato de dados, não código compartilhado" (ver INTEGRATION.md seção 7).
Isso mantém os três repositórios desacoplados; só concordam no formato do
JSON, nunca em uma dependência Python comum.

Formato: JSON Lines (um objeto por linha), chaveado por `record_id`.
Escritas são atômicas (grava em .tmp, depois os.replace()) para que um
leitor nunca veja um arquivo parcialmente escrito.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

STATUS_VALIDOS_FULLTEXT = {"pending", "done", "failed", "not_applicable"}


def normalizar_doi(doi: str) -> str:
    """Mesma normalização usada em descoberta.py e no SPE (record_identity.py):
    lowercase + remove prefixo de URL do doi.org. Mantida aqui também para
    registros que cheguem via registry.jsonl com DOI em formato diferente do
    que descoberta.py já teria normalizado."""
    if not doi:
        return ""
    doi = str(doi).strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.strip()


def normalizar_titulo(titulo: str) -> str:
    if not titulo:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(titulo).lower())


def build_record_id(doi: str | None = None, titulo: str | None = None) -> str | None:
    d = normalizar_doi(doi) if doi else ""
    if d:
        return f"doi:{d}"
    t = normalizar_titulo(titulo) if titulo else ""
    if t:
        return f"title:{t}"
    return None


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def carregar(registry_path: Path) -> dict[str, dict]:
    """Carrega registry.jsonl inteiro em um dict {record_id: registro}.
    Linhas malformadas são puladas com aviso (não derrubam o carregamento)."""
    registros: dict[str, dict] = {}
    if not registry_path.exists():
        return registros
    with open(registry_path, "r", encoding="utf-8") as f:
        for num_linha, linha in enumerate(f, start=1):
            linha = linha.strip()
            if not linha:
                continue
            try:
                rec = json.loads(linha)
            except json.JSONDecodeError as e:
                print(f"! registry: linha {num_linha} malformada em {registry_path}: {e}")
                continue
            rid = rec.get("record_id")
            if rid:
                registros[rid] = rec
    return registros


def salvar(registry_path: Path, registros: dict[str, dict]) -> None:
    """Reescreve o registry inteiro de forma atômica (tmp + os.replace)."""
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = registry_path.with_suffix(registry_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for rid in sorted(registros.keys()):
            f.write(json.dumps(registros[rid], ensure_ascii=False))
            f.write("\n")
    tmp_path.replace(registry_path)


def pendentes_para_download(registry_path: Path) -> list[dict]:
    """Registros com metadata_status=done e fulltext_status em
    (pending, failed) — o que pontodoi deve buscar a seguir."""
    registros = carregar(registry_path)
    return [
        r
        for r in registros.values()
        if r.get("metadata_status") == "done"
        and r.get("fulltext_status") in ("pending", "failed")
    ]


def marcar_fulltext(
    registry_path: Path,
    record_id: str,
    status: str,
    pdf_path: str | None = None,
    resolved_via: str | None = None,
) -> None:
    """Atualiza o bloco fulltext de um único registro e persiste."""
    if status not in STATUS_VALIDOS_FULLTEXT:
        raise ValueError(f"fulltext_status inválido: {status!r}")

    registros = carregar(registry_path)
    rec = registros.get(record_id)
    if rec is None:
        return  # registro sumiu do registry entre a leitura e a escrita — ignora

    rec["fulltext_status"] = status
    if status == "done":
        rec["fulltext"] = {
            "pdf_path": pdf_path,
            "resolved_via": resolved_via,
            "resolved_at": _agora_iso(),
        }
    elif rec.get("fulltext") is None:
        rec["fulltext"] = {"pdf_path": None, "resolved_via": None, "resolved_at": None}
    rec["updated_at"] = _agora_iso()

    registros[record_id] = rec
    salvar(registry_path, registros)


def marcar_fulltext_lote(registry_path: Path, atualizacoes: list[dict]) -> None:
    """Versão em lote de marcar_fulltext — carrega/salva o registry uma vez só.

    `atualizacoes` é uma lista de dicts com chaves: record_id, status,
    pdf_path (opcional), resolved_via (opcional).
    """
    if not atualizacoes:
        return
    registros = carregar(registry_path)
    agora = _agora_iso()

    for upd in atualizacoes:
        rid = upd["record_id"]
        rec = registros.get(rid)
        if rec is None:
            continue
        status = upd["status"]
        if status not in STATUS_VALIDOS_FULLTEXT:
            continue
        rec["fulltext_status"] = status
        if status == "done":
            rec["fulltext"] = {
                "pdf_path": upd.get("pdf_path"),
                "resolved_via": upd.get("resolved_via"),
                "resolved_at": agora,
            }
        rec["updated_at"] = agora
        registros[rid] = rec

    salvar(registry_path, registros)
