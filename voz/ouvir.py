"""Ouvido do Jarvis — captura do microfone e transcrição local.

Transcreve com faster-whisper na própria máquina: nenhum áudio sai daqui.

A escuta é contínua e cortada por silêncio, sem apertar tecla: o nível de ruído
do ambiente é medido na abertura e a fala é reconhecida como o que passa
folgadamente acima desse piso. Um limiar fixo funcionaria na casa de quem
escreveu e falharia em qualquer outra.
"""

from __future__ import annotations

import json
import queue
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TAXA = 16000          # o Whisper espera 16 kHz
BLOCO = 1600          # 100 ms por bloco
CANAIS = 1

CONFIG_PATH = Path(__file__).parent / "config.json"


@dataclass
class Ajustes:
    modelo: str = "small"          # tiny, base, small, medium, large-v3
    idioma: str = "pt"
    silencio_s: float = 1.1        # silêncio que encerra a fala
    fala_minima_s: float = 0.4     # evita disparar com tosse ou clique
    espera_maxima_s: float = 25.0  # trava de segurança por elocução
    margem: float = 3.2            # quantas vezes acima do ruído conta como fala
    dispositivo: str = ""          # trecho do nome, índice, ou vazio p/ padrão

    @classmethod
    def do_arquivo(cls) -> "Ajustes":
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["microfone"]
        except (OSError, KeyError, json.JSONDecodeError):
            return cls()
        return cls(
            modelo=cfg.get("modelo", "small"),
            silencio_s=cfg.get("silencio_s", 1.1),
            margem=cfg.get("margem", 3.2),
            dispositivo=str(cfg.get("dispositivo", "")),
        )


def achar_dispositivo(procurado: str) -> int | None:
    """Resolve nome parcial ou índice para um índice de entrada válido.

    Fixar o dispositivo pelo nome sobrevive à renumeração: o Windows troca os
    índices quando um fone é conectado ou removido.
    """
    import sounddevice as sd

    if not procurado:
        return None

    if procurado.isdigit():
        return int(procurado)

    alvo = procurado.lower()
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and alvo in d["name"].lower():
            return i

    print(f"  [aviso: microfone '{procurado}' não encontrado — usando o padrão]")
    return None


class Ouvido:
    def __init__(self, ajustes: Ajustes | None = None) -> None:
        self.aj = ajustes or Ajustes.do_arquivo()
        self.piso = 0.0
        self._modelo = None
        self.dispositivo = achar_dispositivo(self.aj.dispositivo)

    def nome_dispositivo(self) -> str:
        import sounddevice as sd

        indice = self.dispositivo if self.dispositivo is not None else sd.default.device[0]
        try:
            return sd.query_devices(indice)["name"].strip()
        except Exception:
            return "desconhecido"

    # ------------------------------------------------------------- modelo

    def carregar(self) -> None:
        """Carrega o Whisper. Na primeira vez, baixa o modelo."""
        if self._modelo is not None:
            return

        from faster_whisper import WhisperModel

        print(f"  Carregando o modelo de escuta ({self.aj.modelo})…", flush=True)
        # int8 na CPU: dispensa CUDA e cuDNN, e dá de sobra para ditado curto.
        self._modelo = WhisperModel(self.aj.modelo, device="cpu", compute_type="int8")

    # --------------------------------------------------------- calibração

    def calibrar(self, segundos: float = 1.2) -> None:
        """Mede o ruído de fundo para separar fala de silêncio."""
        import sounddevice as sd

        amostras: list[float] = []
        with sd.InputStream(samplerate=TAXA, channels=CANAIS, dtype="float32",
                            blocksize=BLOCO, device=self.dispositivo) as fluxo:
            fim = time.time() + segundos
            while time.time() < fim:
                bloco, _ = fluxo.read(BLOCO)
                amostras.append(float(np.sqrt(np.mean(bloco ** 2))))

        # Mediana, não média: um estalo isolado não deve elevar o piso.
        self.piso = float(np.median(amostras)) if amostras else 0.0

    @property
    def limiar(self) -> float:
        # O mínimo protege salas muito silenciosas, onde o piso é quase zero
        # e qualquer sussurro passaria a margem.
        return max(self.piso * self.aj.margem, 0.006)

    # ------------------------------------------------------------ escuta

    def escutar(self) -> np.ndarray | None:
        """Espera uma fala e devolve o áudio dela. None se for interrompido."""
        import sounddevice as sd

        fila: queue.Queue[np.ndarray] = queue.Queue()

        def receber(dados, _frames, _tempo, status):
            if status:
                pass  # estouro de buffer não deve derrubar a escuta
            fila.put(dados.copy())

        gravado: list[np.ndarray] = []
        falando = False
        silencio_desde = 0.0
        inicio_fala = 0.0

        with sd.InputStream(samplerate=TAXA, channels=CANAIS, dtype="float32",
                            blocksize=BLOCO, device=self.dispositivo, callback=receber):
            while True:
                try:
                    bloco = fila.get(timeout=0.5)
                except queue.Empty:
                    continue

                nivel = float(np.sqrt(np.mean(bloco ** 2)))
                agora = time.time()

                if nivel > self.limiar:
                    if not falando:
                        falando = True
                        inicio_fala = agora
                        print("  ● ouvindo…", flush=True)
                    silencio_desde = 0.0
                    gravado.append(bloco)

                elif falando:
                    gravado.append(bloco)  # guarda o rabicho da frase

                    if silencio_desde == 0.0:
                        silencio_desde = agora
                    elif agora - silencio_desde >= self.aj.silencio_s:
                        duracao = (agora - inicio_fala) - self.aj.silencio_s
                        if duracao < self.aj.fala_minima_s:
                            # Ruído curto: descarta e volta a esperar.
                            gravado.clear()
                            falando = False
                            silencio_desde = 0.0
                            continue
                        break

                if falando and agora - inicio_fala > self.aj.espera_maxima_s:
                    break

        if not gravado:
            return None
        return np.concatenate(gravado).flatten()

    # -------------------------------------------------------- transcrição

    def transcrever(self, audio: np.ndarray) -> str:
        self.carregar()
        segmentos, _ = self._modelo.transcribe(
            audio,
            language=self.aj.idioma,
            beam_size=5,
            vad_filter=True,  # descarta trechos sem voz antes de decodificar
        )
        return " ".join(s.text.strip() for s in segmentos).strip()


def testar() -> int:
    """Diagnóstico: mostra os microfones e transcreve uma frase."""
    import sounddevice as sd

    from jarvis_voz import preparar_saida

    preparar_saida()

    print("\n  Entradas de áudio disponíveis:\n")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            padrao = " (padrão)" if i == sd.default.device[0] else ""
            print(f"    [{i}] {d['name']}{padrao}")

    ouvido = Ouvido()
    ouvido.carregar()

    print("\n  Medindo o ruído da sala. Fique em silêncio…", flush=True)
    ouvido.calibrar()
    print(f"  Piso de ruído: {ouvido.piso:.4f} · limiar de fala: {ouvido.limiar:.4f}")

    print("\n  Fale alguma coisa:\n", flush=True)
    audio = ouvido.escutar()
    if audio is None:
        print("  Não captei nada.")
        return 1

    print("  Transcrevendo…", flush=True)
    print(f'\n  Você disse: "{ouvido.transcrever(audio)}"\n')
    return 0


if __name__ == "__main__":
    raise SystemExit(testar())
