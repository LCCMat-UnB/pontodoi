"""papers/institucional.py — acesso institucional via navegador (Playwright).

Portado de camada_institucional_playwright.py, preservando as decisões que
já custaram depuração:

  * Perfil persistente NUMA pasta sob o perfil do usuário (não sob
    %LOCALAPPDATA%): o Python da Microsoft Store roda com "identidade de
    pacote" e redireciona gravações lá para uma pasta privada que o Chrome
    (processo separado) não enxerga. Aqui o caminho vem do workspace.
  * Aba "âncora" em about:blank: em modo headed, fechar a última aba às
    vezes derruba o Chromium inteiro no Windows.
  * Modo assistido abre o SEU navegador padrão (não a aba automatizada),
    porque proteções anti-bot (Cloudflare/Akamai/PerimeterX) detectam a
    marca de automação via CDP. Isso NÃO contorna proteção — é você mesmo
    navegando normalmente.

O import do Playwright é preguiçoso (dentro dos métodos), para a CLI abrir
o menu mesmo sem o Playwright instalado.
"""

from __future__ import annotations

import re
import time
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional, Tuple

from . import ui

# Login federado CAFe (CAPES): NÃO reescrevemos URL. Se sua universidade usa
# EZproxy de verdade, defina PREFIXO_PROXY = "%h.algo.br/%p".
PREFIXO_PROXY: str | None = None

SELETORES_BOTAO_PDF = [
    'a:has-text("Download PDF")',
    'a:has-text("View PDF")',
    'a:has-text("Baixar PDF")',
    'button:has-text("PDF")',
    'a[href$=".pdf"]',
]

URL_LOGIN_CAPES = "https://www.periodicos.capes.gov.br"


def abrir_no_navegador_padrao(url: str) -> None:
    """Navegador padrão do sistema, com fallback para WSL (explorer.exe)."""
    if shutil.which("explorer.exe"):
        try:
            subprocess.run(["explorer.exe", url], check=False)
            return
        except Exception:
            pass
    if shutil.which("wslview"):
        try:
            subprocess.run(["wslview", url], check=False)
            return
        except Exception:
            pass
    webbrowser.open(url)


def montar_url_via_proxy(url: str, prefixo_proxy: str) -> str:
    from urllib.parse import urlparse

    partes = urlparse(url)
    host = partes.netloc.replace(".", "-")
    caminho = partes.path.lstrip("/")
    if partes.query:
        caminho += "?" + partes.query
    padrao = prefixo_proxy.replace("%h", host).replace("%p", caminho)
    return padrao if padrao.startswith("http") else f"https://{padrao}"


def perfil_existe(pasta_perfil: Path) -> bool:
    return pasta_perfil.exists()


def fazer_login(pasta_perfil: Path) -> None:
    """Abre um navegador visível para login CAFe/CAPES (uma vez)."""
    from playwright.sync_api import sync_playwright

    pasta_perfil.mkdir(parents=True, exist_ok=True)
    ui.info(f"Pasta de perfil: {pasta_perfil}")
    ui.dica("Passos no navegador que vai abrir:")
    ui.dica("1. Clique em 'Acesso CAFe' (canto superior esquerdo).")
    ui.dica("2. Busque sua universidade, selecione-a e clique em Enviar.")
    ui.dica("3. Faça login com matrícula/SIAPE e senha institucional.")
    ui.dica("4. Abra um artigo pago com sucesso e feche a janela.")
    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(str(pasta_perfil), headless=False)
        pagina = contexto.new_page()
        pagina.goto(URL_LOGIN_CAPES)
        pagina.wait_for_event("close", timeout=0)
        contexto.close()


def _chromium_ausente(erro: Exception) -> bool:
    """Detecta o erro especifico do Playwright quando `playwright install
    chromium` nunca foi rodado -- distinto de outras falhas (perfil
    corrompido, timeout, etc), que continuam sendo reportadas normalmente."""
    return "Executable doesn't exist" in str(erro)


class AcessoInstitucional:
    """Mantém UM navegador autenticado aberto para todo o lote de DOIs."""

    MAGIC_PDF = b"%PDF"

    def __init__(self, pasta_perfil: Path):
        self.pasta_perfil = pasta_perfil
        self._pw = None
        self.contexto = None
        self._pagina_ancora = None
        self.disponivel = pasta_perfil.exists()
        # Distinto de `disponivel=False` por falta de login -- este flag
        # marca "Chromium do Playwright nao instalado", que NAO se resolve
        # tentando reabrir o navegador de novo a cada DOI (ver _abrir_navegador
        # e _relancar_navegador). Sem isso, um lote de N DOIs repetia a mesma
        # stack trace do Playwright N vezes.
        self.chromium_ausente = False

    def __enter__(self):
        if self.disponivel:
            self._abrir_navegador()
        return self

    def __exit__(self, *exc):
        if self.contexto:
            try:
                self.contexto.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass

    def _abrir_navegador(self) -> bool:
        from playwright.sync_api import sync_playwright

        try:
            self._pw = sync_playwright().start()
            self.contexto = self._pw.chromium.launch_persistent_context(
                str(self.pasta_perfil), headless=False
            )
            self._pagina_ancora = self.contexto.new_page()
            try:
                self._pagina_ancora.goto("about:blank")
            except Exception:
                pass
            return True
        except Exception as e:
            if _chromium_ausente(e):
                self.chromium_ausente = True
                ui.erro("[institucional] Chromium do Playwright não encontrado.")
                ui.dica("Rode: playwright install chromium")
                ui.dica("A camada institucional fica desativada para o resto deste lote.")
            else:
                ui.erro(f"[institucional] não consegui abrir o navegador: {e}")
            return False

    def _relancar_navegador(self) -> bool:
        if self.chromium_ausente:
            # Ja avisamos uma vez em _abrir_navegador -- tentar de novo so
            # repetiria a mesma falha a cada DOI do lote.
            return False
        ui.aviso("[institucional] navegador parece fechado — reabrindo...")
        if self.contexto:
            try:
                self.contexto.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self.contexto = None
        self._pw = None
        if self._abrir_navegador():
            ui.ok("[institucional] navegador reaberto.")
            return True
        return False

    def _nova_pagina(self):
        try:
            return self.contexto.new_page()
        except Exception:
            if self._relancar_navegador():
                try:
                    return self.contexto.new_page()
                except Exception as e:
                    ui.erro(f"[institucional] não consegui abrir uma aba: {e}")
            return None

    def tentar_automatico(self, doi: str, destino: Path) -> Tuple[bool, Optional[object]]:
        """(True, None) baixou | (False, pagina) falhou c/ aba aberta | (False, None) erro."""
        if not self.disponivel or self.chromium_ausente:
            return False, None

        pagina = self._nova_pagina()
        if pagina is None:
            return False, None

        try:
            pagina.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=30000)
            if PREFIXO_PROXY:
                pagina.goto(
                    montar_url_via_proxy(pagina.url, PREFIXO_PROXY),
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
            try:
                pagina.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            titulo = pagina.title()
            bloqueado = (
                "__cf_chl" in pagina.url
                or "just a moment" in titulo.lower()
                or "checking your browser" in titulo.lower()
            )
            if bloqueado:
                # Deixa a aba aberta: no modo assistido é a pessoa que resolve.
                return False, pagina

            html = pagina.content()
            m = re.search(
                r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
                html,
                re.IGNORECASE,
            )
            if m and self._baixar_url(m.group(1), destino):
                pagina.close()
                return True, None

            if self._clicar_e_capturar_pdf(pagina, destino):
                pagina.close()
                return True, None

            return False, pagina
        except Exception as e:
            ui.erro(f"[institucional] erro: {e}")
            try:
                pagina.close()
            except Exception:
                pass
            return False, None

    def _baixar_url(self, url: str, destino: Path) -> bool:
        try:
            resp = self.contexto.request.get(url, timeout=30000)
            corpo = resp.body()
            tipo = resp.headers.get("content-type", "").lower()
            if resp.ok and (tipo.count("pdf") or corpo[:4] == b"%PDF"):
                destino.write_bytes(corpo)
                return True
        except Exception:
            pass
        return False

    def _clicar_e_capturar_pdf(self, pagina, destino: Path) -> bool:
        for seletor in SELETORES_BOTAO_PDF:
            try:
                elemento = pagina.locator(seletor).first
                if elemento.count() == 0:
                    continue
            except Exception:
                continue
            try:
                with pagina.expect_download(timeout=8000) as download_info:
                    elemento.click(timeout=5000)
                download_info.value.save_as(str(destino))
                return True
            except Exception:
                pass
            try:
                with self.contexto.expect_page(timeout=8000) as nova_info:
                    elemento.click(timeout=5000)
                nova = nova_info.value
                nova.wait_for_load_state("domcontentloaded", timeout=10000)
                achou = self._baixar_url(nova.url, destino)
                nova.close()
                if achou:
                    return True
            except Exception:
                continue
        return False

    def modo_assistido(self, doi: str, destino: Path, pagina=None, progresso=None) -> str:
        """Abre no navegador padrão e espera o download manual.

        Retorna: 'baixado' | 'pular' | 'sair'.
        """
        url = pagina.url if pagina else f"https://doi.org/{doi}"
        if pagina:
            try:
                pagina.close()
            except Exception:
                pass

        destino_abs = destino.resolve()
        ui.console.print()
        ui.aviso(f"[assistido] abrindo no seu navegador padrão: {url}")
        abrir_no_navegador_padrao(url)
        ui.dica("Baixe o PDF manualmente (faça login/resolva verificações se aparecerem).")
        ui.dica("Salve o arquivo EXATAMENTE como:")
        ui.console.print(f"      [doi]{destino_abs}[/]")

        if progresso is not None:
            progresso.stop()
        try:
            while True:
                ui.dica("Depois de salvar, pressione ENTER — ou digite 'pular' / 'sair'.")
                resposta = ui.perguntar("").strip().lower()
                if resposta == "sair":
                    return "sair"
                if resposta == "pular":
                    return "pular"

                ok, motivo = self._verificar_pdf_baixado(destino)   # <- self.
                if ok:
                    return "baixado"

                ui.erro(f"[assistido] {motivo}")
                ui.dica("Ajuste o arquivo e pressione ENTER de novo, ou digite 'pular' / 'sair'.")
        finally:
            if progresso is not None:
                progresso.start()

    def _verificar_pdf_baixado(self, destino: Path, tentativas: int = 3, espera_seg: float = 1.0) -> tuple[bool, str]:
        """Confere se o arquivo apareceu e parece mesmo um PDF válido."""
        for i in range(tentativas):
            if destino.exists():
                break
            if i < tentativas - 1:
                time.sleep(espera_seg)
        else:
            return False, "arquivo não encontrado no caminho informado."

        try:
            tamanho = destino.stat().st_size
        except OSError:
            return False, "não foi possível ler o arquivo salvo."

        if tamanho == 0:
            return False, "o arquivo existe mas está vazio (0 bytes) — o download pode ter falhado."

        try:
            with destino.open("rb") as f:
                cabecalho = f.read(4)
        except OSError:
            return False, "não foi possível abrir o arquivo para conferência."

        if cabecalho != self.MAGIC_PDF:   # <- self.
            return False, "o conteúdo salvo não parece um PDF (confira se não baixou uma página de erro/login)."

        return True, ""