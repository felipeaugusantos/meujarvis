"""Jarvis falado.

Conversa por texto e ouve a resposta em voz alta, em português, usando a voz
que já vem no Windows — sem nuvem e sem download.

    uv run python voz/jarvis_voz.py

A fala acontece por frase, conforme o modelo gera: o Jarvis começa a responder
antes de terminar de pensar, em vez de deixar um silêncio longo.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

from vozes import escolher

BASE = Path(__file__).parent
SCRIPT_FALA = BASE / "falar.ps1"

SERVIDOR_JARVIS = "http://127.0.0.1:8000/v1/chat/completions"
SERVIDOR_OLLAMA = "http://127.0.0.1:11434/api/chat"
MODELO = "llama3.1:8b"

PERSONA = (
    "Você é o Jarvis, assistente pessoal do Felipe, em Ribeirão Preto. "
    "Responda sempre em português do Brasil. "
    "Suas respostas serão lidas em voz alta: escreva de forma natural e "
    "conversada, sem listas, sem marcadores, sem títulos e sem emojis. "
    "Prefira frases curtas. Seja direto e evite enrolação."
)

# Fim de frase: pontuação seguida de espaço. Evita quebrar em "3.5" ou "Dr. Silva".
FIM_DE_FRASE = re.compile(r"(?<=[.!?…])\s+")


def escolher_servidor(cli: httpx.Client) -> tuple[str, bool]:
    """Usa o servidor do Jarvis se estiver no ar; senão fala direto com o Ollama."""
    try:
        cli.get("http://127.0.0.1:8000/health", timeout=2).raise_for_status()
        return SERVIDOR_JARVIS, True
    except Exception:
        return SERVIDOR_OLLAMA, False


def responder(cli: httpx.Client, url: str, via_jarvis: bool, historico: list[dict]):
    """Gera a resposta em streaming, devolvendo pedaços de texto."""
    if via_jarvis:
        corpo = {"model": MODELO, "messages": historico, "stream": True}
    else:
        corpo = {"model": MODELO, "messages": historico, "stream": True}

    with cli.stream("POST", url, json=corpo, timeout=180) as r:
        r.raise_for_status()
        for linha in r.iter_lines():
            if not linha:
                continue

            if via_jarvis:
                if not linha.startswith("data: "):
                    continue
                dados = linha[6:]
                if dados.strip() == "[DONE]":
                    break
                try:
                    delta = json.loads(dados)["choices"][0].get("delta", {})
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if (pedaco := delta.get("content")):
                    yield pedaco
            else:
                try:
                    d = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if d.get("done"):
                    break
                if (pedaco := d.get("message", {}).get("content")):
                    yield pedaco


def main() -> int:
    if not SCRIPT_FALA.exists():
        print(f"Falta o arquivo {SCRIPT_FALA}", file=sys.stderr)
        return 1

    cli = httpx.Client()
    url, via_jarvis = escolher_servidor(cli)
    origem = "servidor do Jarvis" if via_jarvis else "Ollama direto"

    voz, aviso = escolher()
    historico = [{"role": "system", "content": PERSONA}]

    print("\n  JARVIS — modo de voz")
    print(f"  Modelo: {MODELO} · via {origem}")
    print(f"  Voz: {voz.nome}")
    if aviso:
        print(f"  ({aviso})")
    print("  Escreva e ele responde falando. /sair para encerrar.\n")

    voz.falar("Estou pronto.")

    try:
        while True:
            try:
                entrada = input("Você> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not entrada:
                continue
            if entrada.lower() in {"/sair", "/quit", "sair"}:
                break

            historico.append({"role": "user", "content": entrada})

            print("Jarvis> ", end="", flush=True)
            completo = ""
            pendente = ""

            try:
                for pedaco in responder(cli, url, via_jarvis, historico):
                    print(pedaco, end="", flush=True)
                    completo += pedaco
                    pendente += pedaco

                    # Fala cada frase fechada, mantendo o resto no buffer.
                    partes = FIM_DE_FRASE.split(pendente)
                    if len(partes) > 1:
                        for frase in partes[:-1]:
                            voz.falar(frase)
                        pendente = partes[-1]
            except httpx.HTTPError as erro:
                print(f"\n  [erro ao falar com o modelo: {erro}]")
                historico.pop()
                continue

            if pendente.strip():
                voz.falar(pendente)

            print("\n")
            historico.append({"role": "assistant", "content": completo})

            # Mantém a janela de contexto curta: persona + últimas 12 falas.
            if len(historico) > 13:
                historico = [historico[0]] + historico[-12:]
    finally:
        voz.encerrar()
        cli.close()

    print("Até logo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
