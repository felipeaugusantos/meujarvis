"""Ouvido do Jarvis — captura do microfone e transcrição local.

Transcreve com faster-whisper na própria máquina: nenhum áudio sai daqui.

A escuta é contínua e cortada por silêncio, sem apertar tecla: o nível de ruído
do ambiente é medido na abertura e a fala é reconhecida como o que passa
folgadamente acima desse piso. Um limiar fixo funcionaria na casa de quem
escreveu e falharia em qualquer outra.
"""

from __future__ import annotations

import queue
import sys
import time
from dataclasses import dataclass

import numpy as np

TAXA = 16000          # o Whisper espera 16 kHz
BLOCO = 1600          # 100 ms por bloco
CANAIS = 1


@dataclass
class Ajustes:
    modelo: str = "small"          # tiny, base, small, medium, large-v3
    idioma: str = "pt"
    silencio_s: float = 1.1        # silêncio que encerra a fala
    fala_minima_s: float = 0.4     # evita disparar com tosse ou clique
    espera_maxima_s: float = 25.0  # trava de segurança por elocução
    margem: float = 3.2            # quantas vezes acima do ruído conta como fala


class Ouvido:
    def __init__(self, ajustes: Ajustes | None = None) -> None:
        self.aj = ajustes or Ajustes()
        self.piso = 0.0
        self._modelo = None

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
                            blocksize=BLOCO) as fluxo:
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
                            blocksize=BLOCO, callback=receber):
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
