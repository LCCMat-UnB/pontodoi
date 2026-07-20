"""papers/cli.py — interface de linha de comando (Typer + Rich).

Dois jeitos de usar:
  * Sem argumentos  -> menu interativo colorido (`papers`).
  * Por subcomando   -> `pontodoi buscar "Nome"`, `pontodoi baixar`, etc.

Esta é a única camada que "conhece" o usuário. A lógica vive nos módulos
descoberta / institucional / download / sessions / config.
"""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__, config as cfg, descoberta, registry as reg, sessions, ui

app = typer.Typer(
    name="pontodoi",
    help="Recuperação de papers para pesquisadores(as) brasileiros(as): "
    "Unpaywall + acesso institucional (CAFe/CAPES) + modo assistido.",
    rich_markup_mode="rich",
    no_args_is_help=False,
    add_completion=False,
)


# ============================================================ subcomandos ===

@app.command()
def config(
    email: str = typer.Option(None, "--email", help="Seu e-mail acadêmico."),
    unpaywall: str = typer.Option(None, "--unpaywall", help="E-mail para a API do Unpaywall."),
    instituicao: str = typer.Option(None, "--instituicao", help="Rótulo da sua instituição (CAFe)."),
    workspace: str = typer.Option(
        None, "--workspace", help="Diretório central (sessões, PDFs, perfil do navegador)."
    ),
    mostrar: bool = typer.Option(False, "--mostrar", help="Só mostra a configuração atual."),
):
    """Configura ou mostra o e-mail acadêmico, o diretório central e afins."""
    c = cfg.carregar()
    dados = [email, unpaywall, instituicao, workspace]
    if mostrar or all(v is None for v in dados):
        _mostrar_config(c)
        if not any(dados) and not mostrar:
            _fluxo_config_interativo(c)
        return
    if email is not None:
        c.email_academico = email
    if unpaywall is not None:
        c.email_unpaywall = unpaywall
    if instituicao is not None:
        c.instituicao = instituicao
    if workspace is not None:
        _definir_workspace(c, workspace)
    caminho = cfg.salvar(c)
    ui.ok(f"Configuração salva em {caminho}")


@app.command()
def login():
    """Faz login na camada institucional (CAFe/CAPES) no navegador."""
    _fluxo_login(cfg.carregar())


@app.command()
def buscar(
    nome: str = typer.Argument(None, help="Nome do(a) pesquisador(a)."),
    orcid: str = typer.Option(None, "--orcid", help="ORCID iD (0000-0000-0000-0000)."),
    de: int = typer.Option(None, "--de", help="Ano inicial (inclusive)."),
    ate: int = typer.Option(None, "--ate", help="Ano final (inclusive)."),
):
    """Descobre os DOIs de um(a) pesquisador(a) e cria uma sessão."""
    c = cfg.carregar()
    _exigir_config(c)
    if not nome:
        nome = ui.perguntar("Nome do(a) pesquisador(a)")
    sessao = _fluxo_buscar(c, nome, orcid, de, ate)
    if sessao and ui.confirmar("Baixar os papers desta sessão agora?", padrao=True):
        _fluxo_baixar(c, sessao)


@app.command()
def importar(
    arquivo: str = typer.Argument(None, help="Arquivo .txt com um DOI por linha."),
    nome: str = typer.Option(None, "--nome", help="Rótulo para a sessão."),
):
    """Cria uma sessão a partir de uma lista de DOIs (arquivo ou colada)."""
    c = cfg.carregar()
    _exigir_config(c)
    sessao = _fluxo_importar(c, arquivo, nome)
    if sessao and ui.confirmar("Baixar os papers desta sessão agora?", padrao=True):
        _fluxo_baixar(c, sessao)


@app.command()
def baixar(
    sessao_id: str = typer.Argument(None, help="ID da sessão (padrão: a mais recente)."),
    modo: str = typer.Option("auto", "--modo", help="'auto' ou 'assistido'."),
):
    """Baixa os papers de uma sessão (só o que estiver pendente)."""
    c = cfg.carregar()
    sessao = sessions.carregar(c, sessao_id) if sessao_id else _sessao_mais_recente(c)
    if not sessao:
        ui.erro("Sessão não encontrada. Rode `pontodoi buscar` primeiro.")
        raise typer.Exit(1)
    _fluxo_baixar(c, sessao, modo_inicial=modo)


@app.command()
def sessoes():
    """Lista as sessões existentes."""
    c = cfg.carregar()
    lista = sessions.listar(c)
    if not lista:
        ui.aviso("Nenhuma sessão ainda. Comece com `pontodoi buscar`.")
        return
    ui.tabela_sessoes([s.dados for s in lista])


@app.command()
def continuar(sessao_id: str = typer.Argument(None, help="ID da sessão a retomar.")):
    """Retoma o download de uma sessão de onde parou."""
    c = cfg.carregar()
    sessao = sessions.carregar(c, sessao_id) if sessao_id else _escolher_sessao(c)
    if not sessao:
        ui.erro("Sessão não encontrada.")
        raise typer.Exit(1)
    _fluxo_baixar(c, sessao)


@app.command(name="registry-sync")
def registry_sync(
    registry: str = typer.Option(
        None, "--registry", help="Caminho do registry.jsonl compartilhado (padrão: o salvo em config)."
    ),
    modo: str = typer.Option(
        None, "--modo", help="'auto' ou 'assistido'. Se omitido, pergunta interativamente."
    ),
):
    """Baixa os PDFs pendentes no registry compartilhado (integração com SPE/parsing-papers).

    Lê registry.jsonl, filtra papers com metadata_status=done e
    fulltext_status em (pending, failed), baixa cada um numa sessão dedicada,
    e atualiza fulltext_status no registry a cada item resolvido.
    """
    c = cfg.carregar()
    _exigir_config(c)
    caminho_registry = _resolver_caminho_registry(c, registry)
    if caminho_registry is None:
        raise typer.Exit(1)
    _fluxo_registry_sync(c, caminho_registry, modo)


@app.command()
def versao():
    """Mostra a versão."""
    ui.console.print(f"papers-br [primaria]{__version__}[/]")


# ============================================================== callback ====

@app.callback(invoke_without_command=True)
def principal(ctx: typer.Context):
    """Sem subcomando: abre o menu interativo."""
    if ctx.invoked_subcommand is None:
        menu()


# ============================================================ menu loop =====

OPCOES_MENU = [
    ("Configurar (e-mail, diretório central)", "config"),
    ("Login institucional (CAFe/CAPES)", "login"),
    ("Nova busca (autor / ORCID / período)", "buscar"),
    ("Importar lista de DOIs (arquivo ou colada)", "importar"),
    ("Baixar / continuar uma sessão", "baixar"),
    ("Sincronizar com registry compartilhado (SPE)", "registry-sync"),
    ("Ver sessões", "sessoes"),
    ("Ajuda", "ajuda"),
]


def menu():
    ui.top()
    ui.banner()
    c = cfg.carregar()
    _aviso_pendencias(c)

    while True:
        ui.console.print()
        ui.secao("Menu")
        for i, (rotulo, _) in enumerate(OPCOES_MENU, 1):
            ui.console.print(f"  [aviso]{i}[/]  {rotulo}")
        ui.console.print("  [aviso]0[/]  Sair")

        escolha = ui.escolher_opcao("Escolha uma opção", 0, len(OPCOES_MENU))
        if escolha == 0:
            ui.console.print("[suave]até a próxima![/]")
            return

        acao = OPCOES_MENU[escolha - 1][1]
        c = cfg.carregar()  # recarrega, caso tenha mudado
        try:
            _despachar(acao, c)
        except KeyboardInterrupt:
            ui.aviso("interrompido — voltando ao menu.")
        except Exception as e:  # noqa: BLE001 — menu não pode morrer por um erro
            ui.erro(f"algo deu errado: {e}")


def _despachar(acao: str, c: cfg.Config):
    if acao == "config":
        _mostrar_config(c)
        _fluxo_config_interativo(c)
    elif acao == "login":
        _fluxo_login(c)
    elif acao == "buscar":
        _exigir_config(c)
        nome = ui.perguntar("Nome do(a) pesquisador(a)")
        if not nome:
            return
        orcid = ui.perguntar("ORCID (opcional, Enter para pular)") or None
        de = ui.perguntar_int("Ano inicial (opcional)")
        ate = ui.perguntar_int("Ano final (opcional)")
        sessao = _fluxo_buscar(c, nome, orcid, de, ate)
        if sessao and ui.confirmar("Baixar os papers agora?", padrao=True):
            _fluxo_baixar(c, sessao)
    elif acao == "importar":
        _exigir_config(c)
        sessao = _fluxo_importar(c, None, None)
        if sessao and ui.confirmar("Baixar os papers agora?", padrao=True):
            _fluxo_baixar(c, sessao)
    elif acao == "baixar":
        sessao = _escolher_sessao(c)
        if sessao:
            _fluxo_baixar(c, sessao)
    elif acao == "registry-sync":
        caminho_registry = _resolver_caminho_registry(c, None)
        if caminho_registry:
            _fluxo_registry_sync(c, caminho_registry, modo=None)
    elif acao == "sessoes":
        lista = sessions.listar(c)
        if lista:
            ui.tabela_sessoes([s.dados for s in lista])
        else:
            ui.aviso("Nenhuma sessão ainda.")
    elif acao == "ajuda":
        _ajuda()


# ============================================================ fluxos ========

def _fluxo_config_interativo(c: cfg.Config):
    ui.secao("Configuração")
    c.email_academico = ui.perguntar("E-mail acadêmico", c.email_academico) or c.email_academico
    padrao_unp = c.email_unpaywall or c.email_academico
    c.email_unpaywall = ui.perguntar("E-mail para o Unpaywall", padrao_unp) or padrao_unp
    c.instituicao = ui.perguntar("Instituição (rótulo, opcional)", c.instituicao) or c.instituicao
    novo_ws = ui.perguntar("Diretório central (sessões, PDFs, perfil)", c.workspace)
    if novo_ws and novo_ws != c.workspace:
        _definir_workspace(c, novo_ws)
    caminho = cfg.salvar(c)
    ui.ok(f"Salvo em {caminho}")


def _definir_workspace(c: cfg.Config, caminho: str) -> None:
    """Normaliza o caminho informado, cria o diretório e o grava na config."""
    destino = Path(caminho.strip().strip('"')).expanduser()
    try:
        destino.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        ui.erro(f"não consegui criar o diretório: {e}")
        ui.dica("mantendo o diretório central anterior.")
        return
    c.workspace = str(destino)
    ui.ok(f"Diretório central: {destino}")
    ui.dica("Sessões e downloads novos vão para cá. As sessões antigas ficam onde estavam.")


def _fluxo_login(c: cfg.Config):
    from . import institucional

    pasta = c.dir_workspace() / "perfil_navegador_institucional"
    ui.secao("Login institucional")
    if institucional.perfil_existe(pasta):
        ui.info(f"Já existe um perfil em {pasta}")
        if not ui.confirmar("Refazer o login mesmo assim?", padrao=False):
            return
    try:
        institucional.fazer_login(pasta)
        ui.ok("Login concluído — perfil salvo.")
    except ModuleNotFoundError:
        ui.erro("Playwright não instalado. Rode:")
        ui.dica("pip install playwright  &&  python -m playwright install chromium")
    except Exception as e:  # noqa: BLE001
        # Caso comum: Playwright instalado via pip, mas os binarios do
        # browser nunca foram baixados (`playwright install chromium`) --
        # sem esta checagem, o usuario via a stack trace crua do Playwright
        # dentro de uma caixa ASCII, sem o pontodoi reconhecer o problema.
        if institucional._chromium_ausente(e):
            ui.erro("Chromium do Playwright não encontrado.")
            ui.dica("Rode: playwright install chromium")
        else:
            ui.erro(f"falha no login: {e}")


def _fluxo_buscar(c: cfg.Config, nome: str, orcid, de, ate):
    ui.secao(f"Buscando: {nome}")
    email = c.openalex()

    autor = None
    if orcid:
        autor = descoberta.buscar_autor_por_orcid(orcid, email)

    if not autor:
        candidatos = descoberta.buscar_candidatos(nome, email)
        autor = _escolher_autor(candidatos)

    itens_openalex, itens_orcid = [], []
    orcid_autor = orcid
    if autor:
        ui.info(f"Autor: {autor.get('display_name')} ({autor['id']})")
        with ui.console.status("[primaria]consultando OpenAlex...[/]", spinner="dots"):
            itens_openalex = descoberta.buscar_works_openalex(autor["id"], email, de, ate)
        ui.dica(f"{len(itens_openalex)} trabalho(s) no OpenAlex.")
        orcid_autor = orcid_autor or (autor.get("orcid") or "").replace("https://orcid.org/", "")
    else:
        ui.aviso("Não achei no OpenAlex — seguindo só com ORCID, se informado.")

    if orcid_autor:
        with ui.console.status("[primaria]consultando ORCID...[/]", spinner="dots"):
            itens_orcid = descoberta.buscar_works_orcid(orcid_autor, de, ate)
        ui.dica(f"{len(itens_orcid)} trabalho(s) no ORCID.")

    principais, secundarios = descoberta.consolidar(itens_openalex, itens_orcid)
    if not principais:
        ui.erro("Nenhum DOI encontrado. Confira nome/ORCID/período.")
        return None

    if secundarios:
        ui.aviso(
            f"{len(secundarios)} DOI(s) parecem peças de revisão por pares "
            "(resposta de autor, carta de decisão...) — removidos."
        )

    sessao = sessions.Sessao.criar(
        c, nome, orcid=orcid_autor, author_id=(autor or {}).get("id"), de=de, ate=ate
    )
    sessao.definir_itens(principais)
    ui.ok(f"{len(principais)} DOI(s) salvos na sessão [primaria]{sessao.id}[/]")
    ui.tabela_itens(principais)
    return sessao


def _ler_dois_colados() -> str:
    """Lê DOIs colados no terminal, uma linha por DOI, até uma linha vazia."""
    ui.dica("Cole os DOIs (um por linha). Termine com uma linha em branco.")
    linhas: list[str] = []
    while True:
        try:
            linha = input()
        except EOFError:
            break
        if linha.strip() == "":
            break
        linhas.append(linha)
    return "\n".join(linhas)


def _fluxo_importar(c: cfg.Config, arquivo: str | None, nome: str | None):
    ui.secao("Importar lista de DOIs")

    # Sem arquivo na chamada (ex.: veio do menu): pergunta como fornecer a lista.
    if not arquivo:
        ui.console.print("  [aviso]1[/]  De um arquivo .txt (um DOI por linha)")
        ui.console.print("  [aviso]2[/]  Colar os DOIs aqui no terminal")
        if ui.escolher_opcao("Como quer importar?", 1, 2) == 1:
            arquivo = ui.perguntar("Caminho do arquivo .txt")
            if not arquivo:
                ui.erro("nenhum caminho informado.")
                return None

    if arquivo:
        caminho = Path(arquivo.strip().strip('"')).expanduser()
        if not caminho.exists():
            ui.erro(f"arquivo não encontrado: {caminho}")
            return None
        # utf-8-sig descarta BOM automaticamente se o arquivo tiver.
        texto = caminho.read_text(encoding="utf-8-sig", errors="replace")
        ui.info(f"Lendo {caminho}")
    else:
        texto = _ler_dois_colados()

    itens = descoberta.itens_de_texto(texto)
    if not itens:
        ui.erro("Nenhum DOI válido encontrado na lista.")
        return None

    principais, secundarios = descoberta.consolidar(itens, [])
    if secundarios:
        ui.aviso(
            f"{len(secundarios)} DOI(s) parecem peças de revisão por pares "
            "(resposta de autor, carta de decisão...) — removidos."
        )
    if not principais:
        ui.erro("Depois de filtrar, não sobrou nenhum DOI de artigo.")
        return None

    rotulo = nome or ui.perguntar("Nome para esta sessão", "lista-doi") or "lista-doi"
    sessao = sessions.Sessao.criar(c, rotulo)
    sessao.definir_itens(principais)
    ui.ok(f"{len(principais)} DOI(s) salvos na sessão [primaria]{sessao.id}[/]")
    ui.tabela_itens(principais)
    return sessao


def _fluxo_baixar(
    c: cfg.Config,
    sessao: sessions.Sessao,
    modo_inicial: str | None = None,
    ao_resolver_item=None,
):
    from . import download

    faltando = c.pendencias()
    if "e-mail para o Unpaywall" in faltando:
        ui.aviso("Sem e-mail do Unpaywall — a camada de acesso aberto será pulada.")

    resumo = sessao.resumo()
    ui.secao(f"Download — sessão {sessao.id}")
    ui.info(
        f"pendentes: {resumo['pendente']} | baixados: {resumo['baixado']} | "
        f"não resolvidos: {resumo['nao_resolvido']}"
    )
    if resumo["pendente"] == 0:
        ui.aviso("Nada pendente nesta sessão.")
        return

    modo = modo_inicial
    if modo not in ("auto", "assistido"):
        assistido = ui.confirmar(
            "Habilitar modo assistido? (abre o navegador quando o automático falhar)",
            padrao=False,
        )
        modo = "assistido" if assistido else "auto"

    final = download.executar(sessao, c, modo=modo, ao_resolver_item=ao_resolver_item)
    ui.ok(
        f"Concluído — baixados: {final['baixado']} | "
        f"não resolvidos: {final['nao_resolvido']} | pendentes: {final['pendente']}"
    )
    ui.dica(f"PDFs em: {sessao.pasta_pdfs}")


def _resolver_caminho_registry(c: cfg.Config, informado: str | None) -> Path | None:
    """Decide qual registry.jsonl usar: --registry > config salva > pergunta ao usuário."""
    if informado:
        caminho = Path(informado.strip().strip('"')).expanduser()
    elif c.registry_path:
        caminho = c.caminho_registry()
    else:
        ui.aviso("Nenhum registry compartilhado configurado ainda.")
        entrada = ui.perguntar("Caminho do registry.jsonl (do SPE)")
        if not entrada:
            ui.erro("nenhum caminho informado.")
            return None
        caminho = Path(entrada.strip().strip('"')).expanduser()
        c.registry_path = str(caminho)
        cfg.salvar(c)
        ui.ok(f"Caminho salvo na configuração: {caminho}")

    if not caminho.exists():
        ui.erro(f"registry não encontrado: {caminho}")
        ui.dica("Rode a exportação no SPE primeiro (menu → Export Included Papers to Shared Registry).")
        return None
    return caminho


def _fluxo_registry_sync(c: cfg.Config, caminho_registry: Path, modo: str | None = None):
    """Baixa os PDFs pendentes no registry compartilhado, numa sessão dedicada.

    Reaproveita a mesma máquina de sessão/download já usada por `buscar` e
    `importar` — o registry só entra como fonte alternativa dos itens
    (doi/titulo), no lugar de OpenAlex/ORCID ou de uma lista colada.

    modo=None: pergunta interativamente (auto/assistido) antes de baixar,
    igual ao fluxo normal de `buscar`/`importar` — em vez de herdar um modo
    fixo silenciosamente, o que faria a sessão já sair baixando sem o
    usuário decidir nada.
    """
    ui.secao("Sincronizar com registry compartilhado")

    # Perfil institucional (CAFe/CAPES) vive dentro do workspace *interno* do
    # pontodoi (c.dir_workspace()), que é um campo separado de registry_path
    # (ver config.py). Um usuário que só configurou o registry.jsonl pode
    # nunca ter rodado `pontodoi login` neste workspace específico — sem essa
    # checagem, o download seguia direto para o modo automático puro
    # (só Unpaywall), pulando a camada institucional em silêncio.
    pasta_perfil = c.dir_workspace() / "perfil_navegador_institucional"
    if not pasta_perfil.exists():
        ui.aviso(f"Nenhum perfil institucional (CAFe/CAPES) encontrado em: {c.dir_workspace()}")
        ui.dica("Sem login institucional, só a camada Unpaywall (acesso aberto) fica disponível.")
        if ui.confirmar("Fazer login institucional agora?", padrao=True):
            _fluxo_login(c)

    pendentes = reg.pendentes_para_download(caminho_registry)
    if not pendentes:
        ui.aviso("Nada pendente no registry (metadata_status=done + fulltext_status pendente/falho).")
        return

    ui.info(f"{len(pendentes)} paper(s) prontos para download no registry.")
    itens = [
        {
            "doi": r["doi"],
            "titulo": r.get("title") or "sem título",
            "ano": (r.get("metadata") or {}).get("year"),
            "fonte": "registry:" + ((r.get("metadata") or {}).get("source") or "spe"),
        }
        for r in pendentes
        if r.get("doi")  # download.py opera por DOI — registros só-título ficam de fora
    ]
    sem_doi = len(pendentes) - len(itens)
    if sem_doi:
        ui.aviso(f"{sem_doi} paper(s) do registry não têm DOI — pulados (pontodoi baixa só por DOI).")
    if not itens:
        ui.erro("Nenhum item com DOI para baixar.")
        return

    sessao = sessions.Sessao.criar(c, "registry-sync")
    sessao.definir_itens(itens)
    ui.ok(f"{len(itens)} DOI(s) carregados na sessão [primaria]{sessao.id}[/]")

    # Atualiza o registry item a item, à medida que cada DOI é resolvido —
    # não só ao final do lote inteiro. Um lote de dezenas de papers pode
    # levar minutos (camada institucional/assistida), e se o processo for
    # interrompido no meio (Ctrl+C, queda de rede, terminal fechado), os
    # itens já baixados com sucesso não podem ficar de fora do registry só
    # porque o lote não terminou — senão perde a idempotência: rodar de novo
    # baixaria tudo de novo, mesmo o que já está no disco.
    contagem = {"done": 0, "failed": 0}

    def _ao_resolver(item: dict, resolvido: bool) -> None:
        rid = reg.build_record_id(doi=item["doi"])
        if not rid:
            return
        if resolvido:
            caminho_pdf = sessao.pasta_pdfs / f"{item['doi'].replace('/', '_')}.pdf"
            reg.marcar_fulltext(
                caminho_registry, rid, "done",
                pdf_path=str(caminho_pdf), resolved_via="pontodoi",
            )
            contagem["done"] += 1
        else:
            reg.marcar_fulltext(caminho_registry, rid, "failed")
            contagem["failed"] += 1

    _fluxo_baixar(c, sessao, modo_inicial=modo, ao_resolver_item=_ao_resolver)

    ui.ok(f"Registry atualizado ao longo do download: {contagem['done']} done, {contagem['failed']} failed.")
    ui.dica(f"Próximo passo: rodar o parsing-papers apontando --registry {caminho_registry}")


# ============================================================ auxiliares ====

def _escolher_autor(candidatos: list[dict]) -> dict | None:
    if not candidatos:
        return None
    if len(candidatos) == 1:
        return candidatos[0]
    ui.tabela_candidatos(candidatos)
    escolha = ui.escolher_opcao("Qual é a pessoa certa? (0 = nenhuma)", 0, len(candidatos))
    return None if escolha == 0 else candidatos[escolha - 1]


def _escolher_sessao(c: cfg.Config) -> sessions.Sessao | None:
    lista = sessions.listar(c)
    if not lista:
        ui.aviso("Nenhuma sessão ainda. Comece com uma nova busca.")
        return None
    ui.tabela_sessoes([s.dados for s in lista])
    escolha = ui.escolher_opcao("Qual sessão? (0 = cancelar)", 0, len(lista))
    return None if escolha == 0 else lista[escolha - 1]


def _sessao_mais_recente(c: cfg.Config) -> sessions.Sessao | None:
    lista = sessions.listar(c)
    return lista[0] if lista else None


def _mostrar_config(c: cfg.Config):
    ui.secao("Configuração atual")
    ui.console.print(f"  e-mail acadêmico : [info]{c.email_academico or '—'}[/]")
    ui.console.print(f"  e-mail Unpaywall : [info]{c.unpaywall() or '—'}[/]")
    ui.console.print(f"  instituição      : [info]{c.instituicao or '—'}[/]")
    ui.console.print(f"  workspace        : [info]{c.dir_workspace()}[/]")
    ui.console.print(f"  registry (SPE)   : [info]{c.registry_path or '—'}[/]")
    ui.console.print(f"  arquivo          : [suave]{cfg.ARQUIVO_CONFIG}[/]")


def _exigir_config(c: cfg.Config):
    if not c.esta_configurado():
        ui.aviso("Você ainda não configurou seu e-mail acadêmico.")
        _fluxo_config_interativo(c)


def _aviso_pendencias(c: cfg.Config):
    faltando = c.pendencias()
    if faltando:
        ui.aviso("Pendências de configuração: " + ", ".join(faltando))
        ui.dica("Use a opção 1 do menu para resolver.")


def _ajuda():
    ui.secao("Ajuda")
    ui.console.print(
        "[primaria]papers-br[/] baixa papers de um(a) pesquisador(a) em três camadas, "
        "sempre da mais ética para a mais trabalhosa:\n"
    )
    ui.console.print("  [ok]1.[/] [primaria]Unpaywall[/] — versão de acesso aberto legal (sem login).")
    ui.console.print("  [ok]2.[/] [primaria]Institucional[/] — via seu login CAFe/CAPES, automático.")
    ui.console.print("  [ok]3.[/] [primaria]Assistido[/] — abre o navegador para você baixar à mão.")
    ui.console.print()
    ui.console.print("[aviso]Nunca[/] contorna captcha ou proteção anti-bot.\n")
    ui.secao("Fluxo típico")
    ui.console.print("  1) Configurar e-mail acadêmico")
    ui.console.print("  2) Login institucional (uma vez)")
    ui.console.print("  3) Nova busca → escolhe autor/ORCID/período")
    ui.console.print("     [suave](ou: importar uma lista de DOIs que você já tem)[/]")
    ui.console.print("  4) Baixar (auto ou assistido)")
    ui.console.print("  5) Interrompeu? 'Baixar / continuar' retoma de onde parou.\n")
    ui.secao("Integração com SPE (registry compartilhado)")
    ui.console.print("  Se você usa o [primaria]Synoptic Paper Engine[/] para buscar e triar papers,")
    ui.console.print("  exporte o conjunto incluído no PRISMA para um registry.jsonl (menu do SPE)")
    ui.console.print("  e rode [suave]pontodoi registry-sync[/] aqui para baixar só esses DOIs —")
    ui.console.print("  sem precisar montar a lista manualmente com 'importar'.\n")
    ui.secao("Pela linha de comando")
    ui.console.print("  [suave]pontodoi config --email voce@uni.br[/]")
    ui.console.print("  [suave]pontodoi login[/]")
    ui.console.print('  [suave]pontodoi buscar "Nome" --de 2019 --ate 2024[/]')
    ui.console.print("  [suave]pontodoi importar dois.txt[/]  (ou sem arquivo: cola os DOIs)")
    ui.console.print("  [suave]pontodoi baixar --modo assistido[/]")
    ui.console.print("  [suave]pontodoi registry-sync --registry /caminho/registry.jsonl[/]")
    ui.console.print("  [suave]pontodoi sessoes[/] · [suave]pontodoi continuar <id>[/]")
    ui.console.print("  [suave]pontodoi --help[/] mostra todos os comandos.")


if __name__ == "__main__":
    app()
