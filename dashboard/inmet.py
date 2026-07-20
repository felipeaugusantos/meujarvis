"""Previsão do INMET — o instituto meteorológico brasileiro.

Por que junto com o Open-Meteo, e não no lugar dele:

O INMET publica previsão por cidade, com descrição em português escrita por
quem acompanha o clima daqui ("Muitas nuvens com possibilidade de chuva
isolada"), além de nascer e pôr do sol. Mas não publica temperatura atual nem
umidade para Ribeirão Preto — e não há estação automática na cidade; as mais
próximas são Pradópolis, a 38 km, e São Simão, a 40 km, longe demais para
dizer que está fazendo agora aqui.

Então cada fonte entrega o que sabe: o INMET dá a previsão e a descrição, o
Open-Meteo dá a medição do momento. Se o INMET falhar, o painel volta
inteiro para o Open-Meteo em vez de ficar sem clima.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

PREVISAO_URL = "https://apiprevmet3.inmet.gov.br/previsao/{geocodigo}"

# O INMET derruba a conexão sem responder para clientes sem cabeçalho de
# navegador — não é erro de rede, é filtro de origem.
CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://portal.inmet.gov.br/",
}

# Descrição do INMET -> ícone do painel. A comparação é por trecho, porque o
# texto varia bastante ("Muitas nuvens com possibilidade de chuva isolada").
ICONES = [
    ("tempestade", "tempestade"),
    ("trovoada", "tempestade"),
    ("chuva", "chuva"),
    ("chuvisco", "chuva"),
    ("garoa", "chuva"),
    ("pancada", "chuva"),
    ("nevoeiro", "neblina"),
    ("nevoa", "neblina"),
    ("neblina", "neblina"),
    ("encoberto", "nuvem"),
    ("muitas nuvens", "nuvem"),
    ("nublado", "nuvem"),
    ("poucas nuvens", "nuvem-sol"),
    ("algumas nuvens", "nuvem-sol"),
    ("parcialmente", "nuvem-sol"),
    ("claro", "sol"),
    ("sol", "sol"),
]

_cache: dict[str, tuple[float, Any]] = {}


def _icone(resumo: str) -> str:
    texto = resumo.lower()
    for trecho, icone in ICONES:
        if trecho in texto:
            return icone
    return "nuvem"


def _turno_do_dia(bloco: dict) -> dict:
    """Escolhe o turno que representa o dia.

    A previsão vem dividida em manhã, tarde e noite. Para o cartão vale a
    tarde, quando o tempo costuma se definir — e é o período em que alguém
    olha o painel para decidir se sai.
    """
    for turno in ("tarde", "manha", "noite"):
        if isinstance(bloco.get(turno), dict):
            return bloco[turno]
    return bloco if isinstance(bloco, dict) else {}


def previsao(geocodigo: str, ttl: int = 10800) -> dict | None:
    """Previsão de 5 dias. None quando o INMET não responde.

    Cache de 3 horas: o INMET atualiza poucas vezes ao dia, e insistir mais
    que isso só gasta a banda dele e o tempo do painel.
    """
    chave = f"inmet:{geocodigo}"
    if (guardado := _cache.get(chave)) and time.time() - guardado[0] < ttl:
        return guardado[1]

    try:
        r = httpx.get(
            PREVISAO_URL.format(geocodigo=geocodigo),
            headers=CABECALHOS, timeout=25,
        )
        r.raise_for_status()
        bruto = r.json()
    except (httpx.HTTPError, ValueError):
        return None

    dias = bruto.get(str(geocodigo))
    if not isinstance(dias, dict) or not dias:
        return None

    saida: list[dict] = []
    for data, bloco in dias.items():
        turno = _turno_do_dia(bloco)
        try:
            saida.append({
                "data": data,                      # dd/mm/aaaa
                "resumo": (turno.get("resumo") or "").strip(),
                "max": int(turno["temp_max"]),
                "min": int(turno["temp_min"]),
                "icone": _icone(turno.get("resumo") or ""),
                "vento": turno.get("int_vento", ""),
                "nascer": turno.get("nascer", ""),
                "ocaso": turno.get("ocaso", ""),
            })
        except (KeyError, TypeError, ValueError):
            continue        # um dia malformado não invalida os outros

    if not saida:
        return None

    resultado = {"cidade_geocodigo": geocodigo, "dias": saida}
    _cache[chave] = (time.time(), resultado)
    return resultado
