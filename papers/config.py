"""papers/config.py — configuração persistente do usuário.

Substitui os valores hardcoded dos scripts originais (EMAIL_UNPAYWALL,
EMAIL_CONTATO) por um arquivo TOML no diretório de config do usuário:

  Windows : %APPDATA%\\papers-br\\config.toml
  Linux   : ~/.config/papers-br/config.toml
  macOS   : ~/Library/Application Support/papers-br/config.toml

Leitura via tomllib (stdlib em 3.11+). Escrita é feita à mão (o config é
plano), para não depender de uma lib de escrita de TOML.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _dir_config() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "papers-br"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "papers-br"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "papers-br"


DIR_CONFIG = _dir_config()
ARQUIVO_CONFIG = DIR_CONFIG / "config.toml"

# Espaço de trabalho (sessões, downloads, perfil do navegador). Fica sob o
# perfil do usuário — NÃO sob %LOCALAPPDATA% — porque o Python da Microsoft
# Store redireciona silenciosamente gravações lá para uma pasta privada que o
# Chrome (processo separado) não enxerga. Ver comentário em institucional.py.
DIR_WORKSPACE_PADRAO = Path.home() / "papers-br"


@dataclass
class Config:
    # Identidade acadêmica do usuário.
    email_academico: str = ""
    # E-mail exigido pela API do Unpaywall (pode ser o mesmo acadêmico).
    email_unpaywall: str = ""
    # E-mail de contato do OpenAlex (fila prioritária). Default = acadêmico.
    email_openalex: str = ""
    # Instituição usada no login CAFe (rótulo exibido, informativo).
    instituicao: str = ""
    # Segundos entre requisições no lote de download (gentileza com servidores).
    intervalo_seg: float = 1.0
    # Raiz do espaço de trabalho (sessões + downloads + perfil do navegador).
    workspace: str = str(DIR_WORKSPACE_PADRAO)
    # Caminho do registry.jsonl compartilhado com SPE/parsing-papers (ver
    # INTEGRATION.md no repo synoptic-paper-engine). Vazio = integração não
    # configurada; distinto de `workspace` acima, que é o espaço INTERNO do
    # pontodoi (sessões, perfil do navegador) — não confundir os dois.
    registry_path: str = ""

    # --- derivados / conveniência ------------------------------------------
    def unpaywall(self) -> str:
        return self.email_unpaywall or self.email_academico

    def openalex(self) -> str:
        return self.email_openalex or self.email_academico

    def dir_workspace(self) -> Path:
        return Path(self.workspace).expanduser()

    def caminho_registry(self) -> Path | None:
        return Path(self.registry_path).expanduser() if self.registry_path else None

    def esta_configurado(self) -> bool:
        return bool(self.email_academico)

    def pendencias(self) -> list[str]:
        """Lista o que ainda falta configurar, para avisar o usuário."""
        faltando = []
        if not self.email_academico:
            faltando.append("e-mail acadêmico")
        if not self.unpaywall():
            faltando.append("e-mail para o Unpaywall")
        return faltando


def carregar() -> Config:
    if not ARQUIVO_CONFIG.exists():
        return Config()
    dados = tomllib.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
    conhecidos = {f for f in Config.__dataclass_fields__}
    filtrado = {k: v for k, v in dados.items() if k in conhecidos}
    return Config(**filtrado)


def _formatar_valor(v) -> str:
    if isinstance(v, str):
        escapado = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escapado}"'
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def salvar(config: Config) -> Path:
    DIR_CONFIG.mkdir(parents=True, exist_ok=True)
    linhas = [
        "# Configuração do pontodoi — gerado automaticamente.",
        "# Edite pela CLI (`pontodoi config`) ou manualmente, com cuidado.",
        "",
    ]
    for chave, valor in asdict(config).items():
        linhas.append(f"{chave} = {_formatar_valor(valor)}")
    ARQUIVO_CONFIG.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return ARQUIVO_CONFIG
