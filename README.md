# pontodoi

CLI para pesquisadores(as) brasileiros(as) baixarem papers de um(a) autor(a),
em três camadas — sempre da mais ética/aberta para a mais trabalhosa:

1. **Unpaywall** — versão de acesso aberto legal (sem login, sem captcha).
2. **Acesso institucional** — via seu login CAFe/CAPES num navegador
   autenticado (Playwright), tentado automaticamente.
3. **Modo assistido** — abre o artigo no seu navegador padrão para você
   baixar manualmente quando o automático não dá conta.

**Nunca** contorna captcha ou proteção anti-bot.

## Instalação

**Se você clonou este repositório:**

```bash
pip install -e .
python -m playwright install chromium   # só para a camada institucional
```

**Direto do GitHub, sem clonar:**

```bash
pip install git+https://github.com/LCCMat-UnB/pontodoi
python -m playwright install chromium   # só para a camada institucional
```

Isso disponibiliza o comando `pontodoi`. O passo do Playwright é sempre
necessário (independente de como você instalou) — sem ele, a camada 2
(acesso institucional) fica automaticamente desativada, com aviso claro na
primeira tentativa, mas as camadas 1 (Unpaywall) e 3 (modo assistido)
funcionam normalmente.

## Uso

Menu interativo colorido:

```bash
pontodoi
```

Ou por subcomandos:

```bash
pontodoi config --email voce@universidade.br
pontodoi config --workspace D:\papers      # diretório central (sessões, PDFs, perfil)
pontodoi login                             # login CAFe/CAPES (uma vez)
pontodoi buscar "Nome do Pesquisador" --de 2019 --ate 2024
pontodoi importar dois.txt                 # ou sem arquivo: cola os DOIs no terminal
pontodoi baixar --modo assistido
pontodoi sessoes                           # lista sessões
pontodoi continuar <id>                    # retoma de onde parou
pontodoi registry-sync --registry caminho/registry.jsonl  # integração com SPE/parsing-papers
pontodoi --help
```

## Sessões

Cada busca vira uma **sessão** retomável no **diretório central** (por padrão
`~/papers-br/`, configurável com `pontodoi config --workspace <caminho>` ou pela
opção 1 do menu), em `<workspace>/sessoes/<id>/`, com os DOIs, o status de cada item
(`pendente` / `baixado` / `nao_resolvido`), os PDFs em `papers_baixados/`
e os não resolvidos em `nao_resolvidos.csv` (para pedir via COMUT / EEB).
Interrompeu no meio? `pontodoi continuar <id>` processa só o que falta.

## Estrutura

```
papers/
├── cli.py            menu + subcomandos (Typer/Rich)  — única camada que fala com o usuário
├── ui.py             cores, banner, tabelas, barra de progresso
├── config.py         e-mail acadêmico + APIs (TOML em ~/.config)
├── sessions.py       sessões retomáveis (JSON + CSV por sessão)
├── descoberta.py     DOIs via OpenAlex + ORCID (funções puras)
├── institucional.py  acesso institucional via Playwright (perfil persistente)
├── download.py       orquestração das 3 camadas
└── registry.py       leitura/escrita do registry.jsonl compartilhado (integração SPE/parsing-papers)
```
