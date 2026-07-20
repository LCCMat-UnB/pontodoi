"""papers/descoberta.py — descoberta de DOIs (OpenAlex + ORCID público).

Portado de buscar_pesquisador.py, mas como funções PURAS: recebem
parâmetros, devolvem dados, não imprimem nada nem chamam input(). Toda a
interação (escolher autor homônimo, mostrar tabela) fica na CLI.

Fontes (as mesmas do script original, e pelos mesmos motivos):
  1) OpenAlex  — base aberta, busca por nome, filtro de período nativo.
  2) ORCID     — complementa com trabalhos cadastrados manualmente no perfil.
"""

from __future__ import annotations

import re
import time

import requests

OPENALEX_BASE = "https://api.openalex.org"
ORCID_BASE = "https://pub.orcid.org/v3.0"

# DOIs "filhos" (peças da revisão por pares) que nunca resolvem num PDF de
# artigo — ver justificativa detalhada no buscar_pesquisador.py original.
PADROES_DOI_SECUNDARIO = [
    r"/v\d+/response\d*$",
    r"/v\d+/decision-letter\d*$",
    r"/response\d*$",
    r"/reply\d*$",
    r"/peer-review",
    r"/referee-report\d*$",
    r"/reviewer-report\d*$",
    r"/decision-letter\d*$",
    r"/author-response\d*$",
    r"/sa\d+$",
]


def normalizar_doi(doi: str) -> str:
    doi = doi.strip().lower()
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)


def eh_doi_secundario(doi: str) -> bool:
    doi_lower = doi.lower()
    return any(re.search(p, doi_lower) for p in PADROES_DOI_SECUNDARIO)


def itens_de_texto(texto: str) -> list[dict]:
    """Converte texto solto (um DOI por linha) em itens de sessão.

    Aceita DOIs crus (10.xxxx/yyyy) ou como URL (https://doi.org/...). Ignora
    linhas vazias, comentários (# ...) e o que claramente não é DOI. Deduplica
    preservando a ordem de entrada. 'ano'/'titulo' ficam vazios (só temos o DOI).
    """
    itens: list[dict] = []
    vistos: set[str] = set()
    for linha in texto.splitlines():
        linha = linha.lstrip("﻿").strip()  # BOM que alguns editores prefixam
        if not linha or linha.startswith("#"):
            continue
        doi = normalizar_doi(linha)
        # heurística mínima de "isto parece um DOI": prefixo 10. e uma barra.
        if not re.match(r"^10\.\d{4,9}/\S+$", doi):
            continue
        if doi in vistos:
            continue
        vistos.add(doi)
        itens.append({"doi": doi, "titulo": "sem título", "ano": None, "fonte": "manual"})
    return itens


def buscar_candidatos(nome: str, email: str) -> list[dict]:
    """Autores homônimos no OpenAlex, para a CLI desambiguar."""
    r = requests.get(
        f"{OPENALEX_BASE}/authors",
        params={"search": nome, "per_page": 10, "mailto": email},
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("results", [])


def buscar_autor_por_orcid(orcid: str, email: str) -> dict | None:
    orcid_bare = orcid.strip().replace("https://orcid.org/", "")
    r = requests.get(
        f"{OPENALEX_BASE}/authors",
        params={"filter": f"orcid:{orcid_bare}", "mailto": email},
        timeout=20,
    )
    if r.status_code != 200:
        return None
    resultados = r.json().get("results", [])
    return resultados[0] if resultados else None


def buscar_works_openalex(author_id: str, email: str, de: int | None, ate: int | None) -> list[dict]:
    filtros = [f"author.id:{author_id}"]
    if de:
        filtros.append(f"from_publication_date:{de}-01-01")
    if ate:
        filtros.append(f"to_publication_date:{ate}-12-31")

    itens: list[dict] = []
    cursor = "*"
    while cursor:
        r = requests.get(
            f"{OPENALEX_BASE}/works",
            params={
                "filter": ",".join(filtros),
                "per-page": 200,
                "cursor": cursor,
                "mailto": email,
            },
            timeout=30,
        )
        r.raise_for_status()
        dados = r.json()
        resultados = dados.get("results", [])
        for w in resultados:
            doi = w.get("doi")
            if not doi:
                continue
            doi = normalizar_doi(doi)
            itens.append(
                {
                    "doi": doi,
                    "titulo": w.get("title") or "sem título",
                    "ano": w.get("publication_year"),
                    "fonte": "openalex",
                }
            )
        if not resultados:
            break
        cursor = dados.get("meta", {}).get("next_cursor")
        time.sleep(0.2)  # gentileza com a API pública
    return itens


def buscar_works_orcid(orcid: str, de: int | None, ate: int | None) -> list[dict]:
    orcid = orcid.strip().replace("https://orcid.org/", "")
    try:
        r = requests.get(
            f"{ORCID_BASE}/{orcid}/works", headers={"Accept": "application/json"}, timeout=20
        )
        if r.status_code != 200:
            return []
        grupos = r.json().get("group", [])
    except requests.RequestException:
        return []

    itens: list[dict] = []
    for grupo in grupos:
        resumos = grupo.get("work-summary", [{}])
        resumo = resumos[0] if resumos else {}
        titulo = ((resumo.get("title") or {}).get("title") or {}).get("value", "sem título")
        ano_str = ((resumo.get("publication-date") or {}).get("year") or {}).get("value")
        ano = int(ano_str) if ano_str else None

        doi = None
        for ext_id in (grupo.get("external-ids") or {}).get("external-id", []):
            if ext_id.get("external-id-type", "").lower() == "doi":
                doi = ext_id.get("external-id-value")
                break

        if not doi:
            continue
        if de and ano and ano < de:
            continue
        if ate and ano and ano > ate:
            continue
        itens.append(
            {"doi": normalizar_doi(doi), "titulo": titulo, "ano": ano, "fonte": "orcid"}
        )
    return itens


def consolidar(
    itens_openalex: list[dict], itens_orcid: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Deduplica por DOI (OpenAlex tem prioridade) e separa os secundários.

    Retorna (principais, secundarios), ambos ordenados por ano.
    """
    por_doi: dict[str, dict] = {}
    for it in itens_openalex:
        por_doi[it["doi"]] = it
    for it in itens_orcid:
        por_doi.setdefault(it["doi"], it)

    principais, secundarios = [], []
    for doi, item in por_doi.items():
        (secundarios if eh_doi_secundario(doi) else principais).append(item)

    chave = lambda it: (it.get("ano") or 0)
    return sorted(principais, key=chave), sorted(secundarios, key=chave)
