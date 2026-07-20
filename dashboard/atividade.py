"""Quais aplicativos estão em uso nos aparelhos da rede.

Um celular não conta para a rede o que roda dentro dele. O que dá para
observar é a *consulta de nome*: antes de abrir o Roblox, o aparelho pergunta
onde fica `roblox.com`. Servindo o DNS da casa, dá para inferir o aplicativo a
partir dessas perguntas.

  DECISÃO DE PRIVACIDADE

  Este servidor vê todos os domínios que a casa acessa, mas só registra os que
  casam com a lista de aplicativos abaixo. Todo o resto é encaminhado e
  descartado no mesmo instante — não há log de navegação, nem em memória nem
  em disco.

  Isso responde "as crianças estão no Roblox?" sem construir um arquivo de
  tudo que cada pessoa da casa lê, pesquisa ou assiste. A pergunta que foi
  feita não exige o resto, e o resto não deveria ser coletado só porque é
  tecnicamente possível.

Uso: o roteador precisa apontar o DNS da rede para o IP desta máquina.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
ATIVIDADE_PATH = BASE / "atividade.json"

PORTA_DNS = 53
UPSTREAM = ("1.1.1.1", 53)
TEMPO_ATIVO = 300          # 5 min sem consulta = provavelmente fechou

# Domínio -> nome legível. Só isto é registrado; o resto some.
APLICATIVOS = {
    "roblox.com": "Roblox",
    "rbxcdn.com": "Roblox",
    "minecraft.net": "Minecraft",
    "minecraftservices.com": "Minecraft",
    "mojang.com": "Minecraft",
    "tiktokv.com": "TikTok",
    "tiktokcdn.com": "TikTok",
    "musical.ly": "TikTok",
    "youtube.com": "YouTube",
    "googlevideo.com": "YouTube",
    "ytimg.com": "YouTube",
    "instagram.com": "Instagram",
    "cdninstagram.com": "Instagram",
    "whatsapp.net": "WhatsApp",
    "whatsapp.com": "WhatsApp",
    "netflix.com": "Netflix",
    "nflxvideo.net": "Netflix",
    "discord.com": "Discord",
    "discordapp.com": "Discord",
    "discord.gg": "Discord",
    "twitch.tv": "Twitch",
    "ttvnw.net": "Twitch",
    "garena.com": "Free Fire",
    "freefiremobile.com": "Free Fire",
    "supercell.com": "Supercell",
    "epicgames.com": "Fortnite",
    "unrealengine.com": "Fortnite",
    "steamserver.net": "Steam",
    "steampowered.com": "Steam",
    "spotify.com": "Spotify",
    "scdn.co": "Spotify",
    "facebook.com": "Facebook",
    "fbcdn.net": "Facebook",
    "x.com": "X",
    "twitter.com": "X",
    "twimg.com": "X",
    "pinterest.com": "Pinterest",
    "snapchat.com": "Snapchat",
    "telegram.org": "Telegram",
    "kwai.net": "Kwai",
    "capcut.com": "CapCut",
    "brawlstars.com": "Brawl Stars",
    "clashroyaleapp.com": "Clash Royale",
    "pubgmobile.com": "PUBG Mobile",
    "callofduty.com": "Call of Duty",
}

_trava = threading.Lock()
_estado: dict[str, dict] = {}      # ip -> {app: {"quando": iso, "vezes": n}}
_ativo = False


# --------------------------------------------------------------- persistência


def _gravar() -> None:
    temporario = ATIVIDADE_PATH.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(_estado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporario, ATIVIDADE_PATH)


def _carregar() -> None:
    global _estado
    if not ATIVIDADE_PATH.exists():
        return
    try:
        _estado = json.loads(ATIVIDADE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _estado = {}


# ------------------------------------------------------------------- pacotes


def _nome_consultado(pacote: bytes) -> str:
    """Extrai o domínio da pergunta DNS.

    O nome vem em rótulos com prefixo de tamanho: \\x06google\\x03com\\x00.
    """
    try:
        i = 12                       # pula o cabeçalho fixo
        partes = []
        while i < len(pacote):
            tamanho = pacote[i]
            if tamanho == 0:
                break
            if tamanho & 0xC0:       # ponteiro de compressão: não ocorre aqui
                return ""
            partes.append(pacote[i + 1:i + 1 + tamanho].decode("ascii", "ignore"))
            i += tamanho + 1
        return ".".join(partes).lower()
    except (IndexError, UnicodeDecodeError):
        return ""


def _reconhecer(dominio: str) -> str:
    """Nome do aplicativo, ou vazio se o domínio não interessa."""
    for alvo, nome in APLICATIVOS.items():
        if dominio == alvo or dominio.endswith("." + alvo):
            return nome
    return ""


def _registrar(ip: str, aplicativo: str) -> None:
    agora = datetime.now(timezone.utc).isoformat()
    with _trava:
        doip = _estado.setdefault(ip, {})
        entrada = doip.setdefault(aplicativo, {"vezes": 0})
        entrada["quando"] = agora
        entrada["vezes"] = entrada.get("vezes", 0) + 1
        _gravar()


# ------------------------------------------------------------------ servidor


def _servir() -> None:
    global _ativo

    servidor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        servidor.bind(("0.0.0.0", PORTA_DNS))
    except OSError:
        _ativo = False
        return          # porta 53 ocupada ou sem permissão: segue sem DNS

    _ativo = True

    while True:
        try:
            pacote, remetente = servidor.recvfrom(512)
        except OSError:
            continue

        ip = remetente[0]

        # Encaminha primeiro: a navegação não pode esperar pela análise.
        resposta = b""
        try:
            saida = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            saida.settimeout(4)
            saida.sendto(pacote, UPSTREAM)
            resposta, _ = saida.recvfrom(1024)
            saida.close()
        except OSError:
            pass

        if resposta:
            try:
                servidor.sendto(resposta, remetente)
            except OSError:
                pass

        # Só agora olha o domínio — e só guarda se for da lista.
        dominio = _nome_consultado(pacote)
        if dominio and (aplicativo := _reconhecer(dominio)):
            _registrar(ip, aplicativo)
        # Qualquer outro domínio termina aqui, sem ser escrito em lugar nenhum.


def iniciar() -> None:
    _carregar()
    threading.Thread(target=_servir, daemon=True).start()
    time.sleep(0.4)      # dá tempo de o bind falhar antes de alguém perguntar


def disponivel() -> bool:
    return _ativo


# -------------------------------------------------------------------- consulta


def por_aparelho(ip: str) -> list[dict]:
    """Aplicativos vistos neste aparelho, do mais recente para o mais antigo."""
    with _trava:
        registros = dict(_estado.get(ip, {}))

    agora = time.time()
    saida = []

    for aplicativo, dados in registros.items():
        try:
            quando = datetime.fromisoformat(dados["quando"]).timestamp()
        except (KeyError, ValueError):
            continue
        saida.append({
            "app": aplicativo,
            "quando": dados["quando"],
            "vezes": dados.get("vezes", 0),
            # "Em uso" é inferência, não certeza: o aparelho consultou este
            # domínio há pouco. Pode ser uma notificação em segundo plano.
            "agora": (agora - quando) < TEMPO_ATIVO,
        })

    return sorted(saida, key=lambda a: a["quando"], reverse=True)


def esquecer(ip: str) -> None:
    with _trava:
        _estado.pop(ip, None)
        _gravar()
