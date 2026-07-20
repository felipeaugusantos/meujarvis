"""Presença de aparelhos na rede de casa.

Descobre quem está conectado varrendo a faixa local e lendo a tabela ARP do
Windows, que já mapeia IP para endereço MAC.

O MAC é a identidade estável: o IP muda a cada renovação de DHCP, o nome pode
faltar, mas o MAC do aparelho continua o mesmo. Celulares modernos, porém,
usam MAC aleatório por rede — o endereço é estável naquela rede, mas não é o
MAC de fábrica, e muda se o aparelho esquecer e reconectar ao Wi-Fi.

Nada sai da máquina: a varredura é local e o histórico fica em arquivo.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
APARELHOS_PATH = BASE / "aparelhos.json"

# Fabricantes mais comuns numa casa. A lista oficial da IEEE tem dezenas de
# milhares de linhas; estes prefixos cobrem a maioria do que aparece aqui e
# evitam baixar e manter um arquivo de vários megabytes.
FABRICANTES = {
    "00:1A:11": "Google", "3C:5A:B4": "Google", "F4:F5:D8": "Google",
    "00:03:93": "Apple", "00:0A:27": "Apple", "00:17:F2": "Apple",
    "00:1E:C2": "Apple", "3C:07:54": "Apple", "A4:83:E7": "Apple",
    "F0:18:98": "Apple", "AC:BC:32": "Apple", "DC:A9:04": "Apple",
    "00:12:FB": "Samsung", "00:16:32": "Samsung", "5C:0A:5B": "Samsung",
    "78:1F:DB": "Samsung", "8C:77:12": "Samsung", "E8:50:8B": "Samsung",
    "00:9A:CD": "Huawei", "00:E0:FC": "Huawei", "48:DB:50": "Huawei",
    "50:8F:4C": "Xiaomi", "64:09:80": "Xiaomi", "F8:A4:5F": "Xiaomi",
    "B0:BE:76": "TP-Link", "50:C7:BF": "TP-Link", "C0:25:E9": "TP-Link",
    "00:1D:D8": "Microsoft", "28:18:78": "Microsoft", "7C:1E:52": "Microsoft",
    "00:15:5D": "Microsoft (virtual)",
    "18:74:2E": "Amazon", "44:65:0D": "Amazon", "FC:65:DE": "Amazon",
    "00:24:E4": "Withings", "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi",
    "00:1B:44": "Sony", "00:19:C5": "Sony", "FC:0F:E6": "Sony",
    "48:D0:CF": "Universal Electronics", "00:04:4B": "NVIDIA",
}

_trava = threading.Lock()


# ------------------------------------------------------------------ varredura


def _faixa_local() -> tuple[str, list[str]] | None:
    """Descobre o próprio IP e devolve os endereços da sub-rede /24."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          # não envia nada; só resolve a rota
        meu_ip = s.getsockname()[0]
        s.close()
    except OSError:
        return None

    rede = ipaddress.ip_network(f"{meu_ip}/24", strict=False)
    return meu_ip, [str(ip) for ip in rede.hosts()]


def _cutucar(ip: str) -> None:
    """Um ping curto para que o aparelho apareça na tabela ARP.

    Muitos celulares ignoram ping, mas respondem ao ARP que o próprio sistema
    dispara antes — por isso a resposta ao ping não importa aqui.
    """
    subprocess.run(
        ["ping", "-n", "1", "-w", "350", ip],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _tabela_arp() -> dict[str, str]:
    """IP -> MAC, lidos da tabela ARP do sistema."""
    try:
        saida = subprocess.run(
            ["arp", "-a"], capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    encontrados: dict[str, str] = {}
    padrao = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})")

    for ip, mac in padrao.findall(saida):
        mac = mac.replace("-", ":").upper()
        if mac in {"FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"}:
            continue
        if ip.startswith(("224.", "239.")) or ip.endswith(".255"):
            continue
        encontrados[ip] = mac

    return encontrados


def _nome(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except (socket.herror, socket.gaierror, OSError):
        return ""


def fabricante(mac: str) -> str:
    return FABRICANTES.get(mac[:8], "")


# ------------------------------------------------------------------ histórico


def _ler() -> dict:
    if not APARELHOS_PATH.exists():
        return {}
    try:
        return json.loads(APARELHOS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _gravar(dados: dict) -> None:
    temporario = APARELHOS_PATH.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporario, APARELHOS_PATH)


def varrer() -> dict:
    """Varre a rede e atualiza o histórico. Devolve o estado de cada aparelho."""
    faixa = _faixa_local()
    if faixa is None:
        return {}

    meu_ip, enderecos = faixa

    # 64 sondas simultâneas: a varredura de uma /24 leva poucos segundos em vez
    # de minutos, sem afogar a rede doméstica.
    with ThreadPoolExecutor(max_workers=64) as executor:
        list(executor.map(_cutucar, enderecos))

    vistos = _tabela_arp()
    agora = datetime.now(timezone.utc).isoformat()

    with _trava:
        conhecidos = _ler()

        for ip, mac in vistos.items():
            registro = conhecidos.get(mac, {})
            registro.update({
                "mac": mac,
                "ip": ip,
                "online": True,
                "visto_em": agora,
                "fabricante": registro.get("fabricante") or fabricante(mac),
                "nome": registro.get("apelido") or registro.get("nome") or _nome(ip),
                "eu": ip == meu_ip,
            })
            registro.setdefault("primeira_vez", agora)
            conhecidos[mac] = registro

        # Quem não apareceu nesta rodada fica offline, mas continua listado:
        # saber que um aparelho sumiu é tão útil quanto saber que chegou.
        presentes = set(vistos.values())
        for mac, registro in conhecidos.items():
            if mac not in presentes:
                registro["online"] = False

        _gravar(conhecidos)
        return conhecidos


def listar() -> dict:
    """Estado atual, sem varrer — leitura barata para a tela."""
    with _trava:
        return _ler()


def apelidar(mac: str, apelido: str) -> bool:
    """Dá um nome humano ao aparelho. 'Celular da Ana' vale mais que um MAC."""
    with _trava:
        conhecidos = _ler()
        if mac not in conhecidos:
            return False
        conhecidos[mac]["apelido"] = apelido.strip()[:60]
        conhecidos[mac]["nome"] = apelido.strip()[:60]
        _gravar(conhecidos)
        return True


# ------------------------------------------------------------------- serviço


def vigiar(intervalo: int = 120) -> None:
    """Varre periodicamente em segundo plano."""
    while True:
        try:
            varrer()
        except Exception:
            pass  # rede oscilando não derruba o painel
        time.sleep(intervalo)


def iniciar(intervalo: int = 120) -> None:
    threading.Thread(target=vigiar, args=(intervalo,), daemon=True).start()
