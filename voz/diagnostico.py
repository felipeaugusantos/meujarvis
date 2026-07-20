"""Diagnóstico do microfone.

Grava alguns segundos e mostra o que chegou, para separar três falhas que
parecem iguais na tela: microfone mudo, limiar alto demais, ou transcrição
falhando.

    uv run python voz/diagnostico.py [segundos] [indice_do_dispositivo]
"""

from __future__ import annotations

import sys

import numpy as np
import sounddevice as sd

TAXA = 16000
BLOCO = 1600


def main() -> int:
    segundos = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    indice = int(sys.argv[2]) if len(sys.argv) > 2 else None

    print("\n  Entradas disponíveis:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            marca = " <-- padrão" if i == sd.default.device[0] else ""
            print(f"    [{i}] {d['name']}{marca}")

    alvo = indice if indice is not None else sd.default.device[0]
    print(f"\n  Gravando {segundos:.0f}s do dispositivo [{alvo}]…\n", flush=True)

    niveis: list[float] = []
    blocos: list[np.ndarray] = []

    with sd.InputStream(samplerate=TAXA, channels=1, dtype="float32",
                        blocksize=BLOCO, device=alvo) as fluxo:
        for _ in range(int(segundos * TAXA / BLOCO)):
            bloco, estourou = fluxo.read(BLOCO)
            if estourou:
                pass
            blocos.append(bloco)
            niveis.append(float(np.sqrt(np.mean(bloco ** 2))))

    n = np.array(niveis)
    piso = float(np.median(n))
    pico = float(n.max())

    print(f"  Piso (mediana): {piso:.5f}")
    print(f"  Pico:           {pico:.5f}")
    print(f"  Percentil 90:   {float(np.percentile(n, 90)):.5f}")

    limiar = max(piso * 3.2, 0.006)
    print(f"\n  Limiar usado hoje pelo Jarvis: {limiar:.5f}")

    acima = int((n > limiar).sum())
    print(f"  Blocos acima do limiar: {acima} de {len(n)} "
          f"({acima * 100 // max(1, len(n))}%)")

    print()
    if pico < 0.002:
        print("  >> O microfone não captou praticamente nada.")
        print("     Provável: dispositivo errado, mudo, ou desconectado.")
    elif acima == 0:
        print("  >> Houve som, mas nunca passou do limiar.")
        print(f"     Sugestão: reduzir 'margem' em ouvir.py, ou usar "
              f"limiar ~{pico * 0.4:.4f}.")
    else:
        print("  >> O microfone está captando e a fala passa do limiar.")
        print("     Se ainda assim não responde, o problema é a transcrição.")

    # Transcreve o que foi gravado, fechando o diagnóstico ponta a ponta.
    audio = np.concatenate(blocos).flatten()
    if pico >= 0.002:
        print("\n  Transcrevendo o que foi gravado…", flush=True)
        from faster_whisper import WhisperModel

        modelo = WhisperModel("small", device="cpu", compute_type="int8")
        segmentos, _ = modelo.transcribe(audio, language="pt", vad_filter=True)
        texto = " ".join(s.text.strip() for s in segmentos).strip()
        print(f'\n  Transcrição: "{texto or "(vazio)"}"\n')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
