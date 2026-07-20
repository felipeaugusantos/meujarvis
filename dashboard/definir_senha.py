"""Define a senha do painel.

    uv run python dashboard/definir_senha.py

A senha é pedida sem eco e guardada como hash com sal. O texto puro não passa
por linha de comando — argumentos ficam no histórico do terminal e na lista de
processos, visíveis a qualquer programa da máquina.
"""

from __future__ import annotations

import getpass
import sys

from autenticacao import SENHA_PATH, definir_senha, tem_senha


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    print("\n  Senha do painel do Jarvis")
    print("  Ela passa a ser exigida em toda visita, inclusive pelo túnel.\n")

    if tem_senha():
        print("  Já existe uma senha definida. Continuar substitui a atual.\n")

    senha = getpass.getpass("  Nova senha: ")
    if len(senha) < 6:
        print("\n  Muito curta. Use ao menos 6 caracteres.\n")
        return 1

    if senha != getpass.getpass("  Repita a senha: "):
        print("\n  As senhas não conferem.\n")
        return 1

    definir_senha(senha)
    print(f"\n  Senha gravada em {SENHA_PATH.name}.")
    print("  Reinicie o painel para que passe a valer.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
