"""Canais de fala do Jarvis.

Duas implementações da mesma interface:

- ElevenLabs, quando existe chave — voz natural, custa por caractere;
- Windows SAPI, sempre disponível — robótica, offline, gratuita.

Ambas falam de forma assíncrona: `falar()` enfileira e devolve na hora, para que
o modelo continue gerando enquanto a frase anterior toca.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from queue import Queue

import httpx

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

# O código HTTP diz o que aconteceu; a mensagem precisa dizer o que fazer.
MOTIVOS = {
    401: "chave da ElevenLabs inválida",
    403: "chave sem permissão para esta voz",
    404: "voice_id não encontrado",
    422: "texto recusado pela ElevenLabs",
    429: "cota da ElevenLabs esgotada",
}


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def limpar(texto: str) -> str:
    """Tira marcação que não faz sentido pronunciar."""
    texto = re.sub(r"```.*?```", " ", texto, flags=re.DOTALL)
    texto = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", texto)
    texto = re.sub(r"[*_`#>]", "", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _powershell(script: Path) -> subprocess.Popen:
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )


class VozWindows:
    """Fala pela voz que acompanha o Windows. Sem rede, sem custo."""

    nome = "Windows (Maria)"

    def __init__(self) -> None:
        self.proc = _powershell(BASE / "falar.ps1")

    def falar(self, texto: str) -> None:
        texto = limpar(texto)
        if not texto or not self.proc.stdin:
            return
        # base64: acentos não dependem da code page e nada vira comando.
        codificado = base64.b64encode(texto.encode("utf-8")).decode("ascii")
        try:
            self.proc.stdin.write(codificado + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def encerrar(self) -> None:
        _encerrar(self.proc)


class VozElevenLabs:
    """Fala pela ElevenLabs.

    A síntese roda numa thread: baixar o áudio leva de 0,5 a 2 segundos e não
    pode bloquear a geração do texto. As frases entram numa fila e são tocadas
    em ordem por um único processo.
    """

    nome = "ElevenLabs"

    # Falhas seguidas antes de desistir de vez da nuvem. Uma oscilação de rede
    # não deveria custar a voz boa pelo resto da conversa; cota esgotada, sim.
    LIMITE_FALHAS = 3

    def __init__(self, chave: str, cfg: dict) -> None:
        self.chave = chave
        self.cfg = cfg
        self.cli = httpx.Client(timeout=60)
        self.fila: Queue[str | None] = Queue()
        self.tocador = _powershell(BASE / "tocar.ps1")
        self.reserva: VozWindows | None = None
        self.falhas = 0
        self.desistiu = False
        self.thread = threading.Thread(target=self._trabalhar, daemon=True)
        self.thread.start()

    def _maria(self) -> "VozWindows":
        """Voz do Windows, criada só quando precisa."""
        if self.reserva is None:
            self.reserva = VozWindows()
        return self.reserva

    def _sintetizar(self, texto: str) -> tuple[bytes | None, str]:
        """Devolve o áudio e, em caso de falha, o motivo em português."""
        try:
            r = self.cli.post(
                ELEVEN_URL.format(voice_id=self.cfg["voice_id"]),
                headers={"xi-api-key": self.chave, "Content-Type": "application/json"},
                params={"output_format": "mp3_44100_128"},
                json={
                    "text": texto,
                    "model_id": self.cfg["modelo"],
                    "voice_settings": {
                        "stability": self.cfg["estabilidade"],
                        "similarity_boost": self.cfg["similaridade"],
                        "speed": self.cfg["velocidade"],
                    },
                },
            )
            r.raise_for_status()
            return r.content, ""
        except httpx.HTTPStatusError as erro:
            return None, MOTIVOS.get(erro.response.status_code, f"erro {erro.response.status_code}")
        except httpx.HTTPError:
            return None, "sem resposta da ElevenLabs"

    def _trabalhar(self) -> None:
        while True:
            texto = self.fila.get()
            if texto is None:
                break

            # Já desistiu da nuvem: tudo sai pela Maria.
            if self.desistiu:
                self._maria().falar(texto)
                continue

            audio, motivo = self._sintetizar(texto)

            if audio is None:
                self.falhas += 1
                self._maria().falar(texto)  # a frase não se perde

                if self.falhas >= self.LIMITE_FALHAS:
                    self.desistiu = True
                    print(
                        f"\n  [voz: {motivo} — passando para a Maria pelo resto "
                        f"da conversa]\n",
                        flush=True,
                    )
                elif self.falhas == 1:
                    print(f"\n  [voz: {motivo} — esta frase saiu pela Maria]\n", flush=True)
                continue

            self.falhas = 0  # voltou a funcionar

            fd, caminho = tempfile.mkstemp(suffix=".mp3", prefix="jarvis_")
            with os.fdopen(fd, "wb") as f:
                f.write(audio)

            try:
                if self.tocador.stdin:
                    self.tocador.stdin.write(caminho + "\n")
                    self.tocador.stdin.flush()
            except (BrokenPipeError, OSError):
                break

    def falar(self, texto: str) -> None:
        texto = limpar(texto)
        if texto:
            self.fila.put(texto)

    def encerrar(self) -> None:
        self.fila.put(None)
        self.thread.join(timeout=30)
        _encerrar(self.tocador)
        if self.reserva is not None:
            self.reserva.encerrar()
        self.cli.close()


def _encerrar(proc: subprocess.Popen) -> None:
    try:
        if proc.stdin:
            proc.stdin.write("__SAIR__\n")
            proc.stdin.flush()
        proc.wait(timeout=15)
    except Exception:
        proc.kill()


def carregar_chave() -> str:
    """Chave da ElevenLabs, do ambiente ou do .env do projeto."""
    if (chave := os.environ.get("ELEVENLABS_API_KEY", "").strip()):
        return chave

    env = BASE.parent / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith("ELEVENLABS_API_KEY="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def escolher():
    """Melhor voz disponível, com aviso do que levou à escolha."""
    cfg = config()
    preferido = cfg.get("backend", "auto")

    if preferido in {"auto", "elevenlabs"}:
        if (chave := carregar_chave()):
            return VozElevenLabs(chave, cfg["elevenlabs"]), None
        if preferido == "elevenlabs":
            return VozWindows(), (
                "backend elevenlabs pedido, mas ELEVENLABS_API_KEY não foi "
                "encontrada — usando a voz do Windows"
            )
        return VozWindows(), (
            "sem ELEVENLABS_API_KEY — usando a voz do Windows"
        )

    return VozWindows(), None
