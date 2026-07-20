"""Painel de parede do Jarvis.

App independente do OpenJarvis para não conflitar com atualizações do upstream.
Serve uma tela de quiosque com relógio, clima, tarefas e notícias.

    uv run python dashboard/app.py
"""

from __future__ import annotations

import json
import os
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import atividade
import autenticacao
import rede

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"
TASKS_PATH = BASE / "tarefas.json"

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Códigos WMO usados pelo Open-Meteo, agrupados no que importa para a tela.
WMO = {
    0: ("Céu limpo", "sol"),
    1: ("Predominantemente limpo", "sol"),
    2: ("Parcialmente nublado", "nuvem-sol"),
    3: ("Nublado", "nuvem"),
    45: ("Neblina", "neblina"),
    48: ("Neblina com gelo", "neblina"),
    51: ("Garoa fraca", "chuva"),
    53: ("Garoa", "chuva"),
    55: ("Garoa forte", "chuva"),
    61: ("Chuva fraca", "chuva"),
    63: ("Chuva", "chuva"),
    65: ("Chuva forte", "chuva"),
    71: ("Neve fraca", "neve"),
    73: ("Neve", "neve"),
    75: ("Neve forte", "neve"),
    80: ("Pancadas de chuva", "chuva"),
    81: ("Pancadas de chuva", "chuva"),
    82: ("Pancadas fortes", "chuva"),
    95: ("Tempestade", "tempestade"),
    96: ("Tempestade com granizo", "tempestade"),
    99: ("Tempestade com granizo", "tempestade"),
}

app = FastAPI(title="Painel Jarvis", docs_url=None, redoc_url=None)

_cache: dict[str, tuple[float, Any]] = {}

# Endereços que não exigem sessão: a própria tela de entrada e o que ela usa.
LIVRES = {"/entrar", "/static/entrar.css", "/favicon.ico"}


@app.middleware("http")
async def exigir_sessao(requisicao: Request, seguir):
    """Barra tudo enquanto não houver sessão — mas só quando há senha definida.

    Sem senha configurada o painel segue aberto, como sempre foi em rede
    local. A proteção liga junto com o túnel, que é quando passa a fazer
    diferença. Assim ninguém fica trancado para fora do próprio painel por
    causa de uma mudança que não pediu.
    """
    caminho = requisicao.url.path

    if not autenticacao.tem_senha() or caminho in LIVRES:
        return await seguir(requisicao)

    if autenticacao.cookie_valido(requisicao.cookies.get(autenticacao.COOKIE)):
        return await seguir(requisicao)

    # Navegador pedindo página recebe a tela de entrada; chamada de API recebe
    # 401, para o JavaScript saber que a sessão caiu em vez de renderizar HTML.
    if caminho.startswith("/api/"):
        return JSONResponse({"detail": "sessão expirada"}, status_code=401)

    return RedirectResponse("/entrar", status_code=303)


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def cached(chave: str, ttl: int):
    """Devolve o valor em cache se ainda válido, senão None."""
    entrada = _cache.get(chave)
    if entrada and time.time() - entrada[0] < ttl:
        return entrada[1]
    return None


def guardar(chave: str, valor: Any) -> Any:
    _cache[chave] = (time.time(), valor)
    return valor


# --------------------------------------------------------------------- clima


async def coordenadas(cidade: str, pais: str) -> tuple[float, float, str]:
    chave = f"geo:{cidade}:{pais}"
    if (hit := cached(chave, 86400 * 30)) is not None:
        return hit

    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.get(
            GEOCODE_URL,
            params={"name": cidade, "count": 1, "language": "pt", "format": "json"},
        )
        r.raise_for_status()
        dados = r.json().get("results") or []

    if not dados:
        raise HTTPException(404, f"Cidade não encontrada: {cidade}")

    p = dados[0]
    return guardar(chave, (p["latitude"], p["longitude"], p["name"]))


@app.get("/api/clima")
async def clima():
    cfg = config()
    ttl = cfg["atualizacao_segundos"]["clima"]
    if (hit := cached("clima", ttl)) is not None:
        return hit

    lat, lon, nome = await coordenadas(cfg["cidade"], cfg["pais"])

    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "timezone": "auto",
                "forecast_days": 4,
            },
        )
        r.raise_for_status()
        d = r.json()

    atual = d["current"]
    diario = d["daily"]
    descricao, icone = WMO.get(atual["weather_code"], ("—", "nuvem"))

    proximos = [
        {
            "data": diario["time"][i],
            "max": round(diario["temperature_2m_max"][i]),
            "min": round(diario["temperature_2m_min"][i]),
            "icone": WMO.get(diario["weather_code"][i], ("—", "nuvem"))[1],
        }
        for i in range(1, min(4, len(diario["time"])))
    ]

    return guardar(
        "clima",
        {
            "cidade": nome,
            "temperatura": round(atual["temperature_2m"]),
            "sensacao": round(atual["apparent_temperature"]),
            "umidade": atual["relative_humidity_2m"],
            "descricao": descricao,
            "icone": icone,
            "maxima": round(diario["temperature_2m_max"][0]),
            "minima": round(diario["temperature_2m_min"][0]),
            "proximos": proximos,
        },
    )


# ------------------------------------------------------------------ notícias


def _texto(node, *nomes: str) -> str:
    """Primeiro texto não vazio entre as tags candidatas (RSS ou Atom)."""
    for nome in nomes:
        el = node.find(nome)
        if el is not None:
            if el.text and el.text.strip():
                return el.text.strip()
            if (href := el.get("href")):
                return href
    return ""


@app.get("/api/noticias")
async def noticias():
    cfg = config()
    ttl = cfg["atualizacao_segundos"]["noticias"]
    if (hit := cached("noticias", ttl)) is not None:
        return hit

    itens: list[dict] = []
    ns = "{http://www.w3.org/2005/Atom}"

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as cli:
        for feed in cfg["feeds"]:
            try:
                r = await cli.get(feed["url"])
                r.raise_for_status()
                raiz = ET.fromstring(r.content)
            except Exception:
                continue  # feed fora do ar não derruba a tela

            entradas = raiz.findall(".//item") or raiz.findall(f".//{ns}entry")
            for e in entradas[:6]:
                titulo = _texto(e, "title", f"{ns}title")
                if not titulo:
                    continue
                itens.append(
                    {
                        "titulo": titulo,
                        "link": _texto(e, "link", f"{ns}link"),
                        "fonte": feed["nome"],
                        "data": _texto(e, "pubDate", "published", f"{ns}updated"),
                    }
                )

    return guardar("noticias", {"itens": itens[: cfg["max_noticias"]]})


# ------------------------------------------------------------------- tarefas


class NovaTarefa(BaseModel):
    texto: str


class MudarTarefa(BaseModel):
    feita: bool


def ler_tarefas() -> list[dict]:
    if not TASKS_PATH.exists():
        return []
    try:
        dados = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Arquivo ilegível não é arquivo vazio. Devolver [] aqui fazia a
        # gravação seguinte apagar tudo de verdade: uma leitura ruim virava
        # perda permanente. Preserva o original para inspeção e recusa.
        estrago = TASKS_PATH.with_suffix(".corrompido")
        try:
            estrago.write_bytes(TASKS_PATH.read_bytes())
        except OSError:
            pass
        raise HTTPException(500, "arquivo de tarefas ilegível; nada foi alterado")

    return dados if isinstance(dados, list) else []


def gravar_tarefas(tarefas: list[dict]) -> None:
    """Grava de forma atômica.

    Escrever direto no destino deixa uma janela em que o arquivo está pela
    metade: quem ler nesse instante vê JSON inválido. Grava ao lado e troca —
    no Windows, os.replace também é atômico.
    """
    temporario = TASKS_PATH.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(tarefas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporario, TASKS_PATH)


@app.get("/api/tarefas")
def listar_tarefas():
    return {"itens": ler_tarefas()}


@app.post("/api/tarefas")
def criar_tarefa(nova: NovaTarefa):
    texto = nova.texto.strip()
    if not texto:
        raise HTTPException(400, "Texto vazio")

    tarefas = ler_tarefas()
    tarefas.append(
        {
            "id": uuid.uuid4().hex[:8],
            "texto": texto[:200],
            "feita": False,
            "criada": datetime.now(timezone.utc).isoformat(),
        }
    )
    gravar_tarefas(tarefas)
    return {"itens": tarefas}


@app.patch("/api/tarefas/{tarefa_id}")
def alternar_tarefa(tarefa_id: str, mudanca: MudarTarefa):
    tarefas = ler_tarefas()
    for t in tarefas:
        if t["id"] == tarefa_id:
            t["feita"] = mudanca.feita
            gravar_tarefas(tarefas)
            return {"itens": tarefas}
    raise HTTPException(404, "Tarefa não encontrada")


@app.delete("/api/tarefas/{tarefa_id}")
def remover_tarefa(tarefa_id: str):
    tarefas = ler_tarefas()
    restantes = [t for t in tarefas if t["id"] != tarefa_id]
    if len(restantes) == len(tarefas):
        raise HTTPException(404, "Tarefa não encontrada")
    gravar_tarefas(restantes)
    return {"itens": restantes}


# -------------------------------------------------- e-mail e agenda (futuro)


@app.get("/api/integracoes")
def integracoes():
    """Estado das fontes que dependem de credencial do Google.

    Enquanto não houver OAuth configurado, a tela mostra o bloco como
    pendente em vez de esconder — assim fica claro o que falta ligar.
    """
    conectores = Path.home() / ".openjarvis" / "connectors"
    tem_google = (conectores / "gdrive.json").exists()
    return {
        "email": {"configurado": tem_google, "nao_lidos": 0, "itens": []},
        "agenda": {"configurado": tem_google, "itens": []},
    }


# ------------------------------------------------------------------ sinais


@app.get("/api/sistema")
def sistema():
    """Sinais vitais da máquina que hospeda o Jarvis.

    Cada bloco degrada sozinho: sem GPU NVIDIA, a tela mostra o resto em vez
    de ficar vazia.
    """
    dados: dict[str, Any] = {"cpu": None, "ram": None, "gpu": None, "vram": None}

    try:
        import psutil

        dados["cpu"] = psutil.cpu_percent(interval=0.15)
        dados["ram"] = psutil.virtual_memory().percent
    except Exception:
        pass

    try:
        import pynvml

        pynvml.nvmlInit()
        placa = pynvml.nvmlDeviceGetHandleByIndex(0)
        dados["gpu"] = pynvml.nvmlDeviceGetUtilizationRates(placa).gpu
        memoria = pynvml.nvmlDeviceGetMemoryInfo(placa)
        dados["vram"] = round(memoria.used / memoria.total * 100, 1)
        nome = pynvml.nvmlDeviceGetName(placa)
        dados["placa"] = nome.decode() if isinstance(nome, bytes) else nome
    except Exception:
        pass

    # O modelo local responde? É o sinal que diz se o Jarvis está de fato vivo.
    try:
        with httpx.Client(timeout=2) as cli:
            cli.get("http://127.0.0.1:11434/api/tags").raise_for_status()
        dados["modelo"] = "online"
    except Exception:
        dados["modelo"] = "offline"

    return dados


# --------------------------------------------------------------------- rede


class Apelido(BaseModel):
    apelido: str


@app.get("/api/rede")
def rede_estado():
    """Aparelhos vistos na rede local, com quem está online agora."""
    aparelhos = sorted(
        rede.listar().values(),
        # Online primeiro; dentro de cada grupo, por IP numérico.
        key=lambda a: (not a.get("online"), [int(p) for p in a.get("ip", "0.0.0.0").split(".")]),
    )

    for aparelho in aparelhos:
        usos = atividade.por_aparelho(aparelho.get("ip", ""))
        aparelho["apps"] = usos[:4]
        aparelho["app_agora"] = next((u["app"] for u in usos if u["agora"]), "")

    return {
        "itens": aparelhos,
        "online": sum(1 for a in aparelhos if a.get("online")),
        "total": len(aparelhos),
        # A tela precisa saber se o DNS está de pé: sem ele, a ausência de
        # aplicativos significa "não estou medindo", não "ninguém está usando".
        "dns": atividade.disponivel(),
    }


@app.post("/api/rede/varrer")
def rede_varrer():
    rede.varrer()
    return rede_estado()


@app.patch("/api/rede/{mac}")
def rede_apelidar(mac: str, corpo: Apelido):
    if not rede.apelidar(mac.upper(), corpo.apelido):
        raise HTTPException(404, "aparelho não encontrado")
    return rede_estado()


# --------------------------------------------------------------------- tela

app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/face")
def face():
    """Modo cockpit em tela cheia."""
    return FileResponse(BASE / "static" / "face.html")


# ------------------------------------------------------------------- entrada

TELA_ENTRADA = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis</title><link rel="stylesheet" href="/static/entrar.css"></head>
<body><form method="post" action="/entrar">
  <h1>JARVIS</h1>
  <input type="password" name="senha" placeholder="senha" autofocus
         autocomplete="current-password" required>
  <button type="submit">Entrar</button>
  {erro}
</form></body></html>"""


@app.get("/entrar", response_class=HTMLResponse)
def tela_entrada():
    return TELA_ENTRADA.format(erro="")


@app.post("/entrar")
def entrar(senha: str = Form(...)):
    if not autenticacao.conferir_senha(senha):
        # Pausa curta: transforma um ataque de força bruta em algo inviável
        # sem punir quem só errou a senha uma vez.
        time.sleep(1.5)
        return HTMLResponse(
            TELA_ENTRADA.format(erro='<p class="erro">Senha incorreta.</p>'),
            status_code=401,
        )

    resposta = RedirectResponse("/", status_code=303)
    resposta.set_cookie(
        autenticacao.COOKIE,
        autenticacao.criar_cookie(),
        max_age=autenticacao.VALIDADE,
        httponly=True,      # fora do alcance de JavaScript
        samesite="lax",
    )
    return resposta


@app.on_event("startup")
def ligar_vigia():
    """Varre a rede a cada 2 minutos e sobe o DNS, ambos em segundo plano."""
    rede.iniciar(intervalo=120)
    atividade.iniciar()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
