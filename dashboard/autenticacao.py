"""Autenticação do painel.

Existe por causa do túnel: em rede local a exposição é aceitável, mas com um
endereço público qualquer pessoa que o descubra leria as tarefas e poderia
apagá-las. Endereço difícil de adivinhar não é segredo — é obscuridade.

Uma senha só, guardada como hash, trocada por um cookie assinado. Não há
cadastro nem múltiplos usuários: é o painel de uma casa, não um serviço.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

BASE = Path(__file__).parent
SEGREDO_PATH = BASE / ".sessao"           # chave de assinatura do cookie
SENHA_PATH = BASE / ".senha"              # hash da senha

COOKIE = "jarvis_sessao"
VALIDADE = 60 * 60 * 24 * 30              # 30 dias: o tablet não faz login toda hora


def _segredo() -> bytes:
    """Chave de assinatura, criada na primeira execução e reutilizada.

    Gerar a cada início invalidaria todas as sessões a cada reinício do
    servidor — o tablet pediria senha sempre.
    """
    if SEGREDO_PATH.exists():
        return SEGREDO_PATH.read_bytes()

    chave = secrets.token_bytes(32)
    SEGREDO_PATH.write_bytes(chave)
    try:  # sem efeito no Windows, mas correto onde houver permissões POSIX
        os.chmod(SEGREDO_PATH, 0o600)
    except OSError:
        pass
    return chave


def definir_senha(senha: str) -> None:
    """Guarda a senha como hash com sal. O texto puro nunca toca o disco."""
    sal = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, 200_000)
    SENHA_PATH.write_text(f"{sal.hex()}:{digest.hex()}", encoding="utf-8")
    try:
        os.chmod(SENHA_PATH, 0o600)
    except OSError:
        pass


def tem_senha() -> bool:
    return SENHA_PATH.exists()


def conferir_senha(senha: str) -> bool:
    if not SENHA_PATH.exists():
        return False
    try:
        sal_hex, esperado = SENHA_PATH.read_text(encoding="utf-8").strip().split(":")
    except ValueError:
        return False

    digest = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal_hex), 200_000)
    # compare_digest: o tempo de comparação não revela quantos caracteres bateram.
    return hmac.compare_digest(digest.hex(), esperado)


def criar_cookie() -> str:
    expira = int(time.time()) + VALIDADE
    corpo = str(expira)
    assinatura = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
    return f"{corpo}.{assinatura}"


def cookie_valido(valor: str | None) -> bool:
    if not valor or "." not in valor:
        return False

    corpo, _, assinatura = valor.rpartition(".")
    esperado = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura, esperado):
        return False

    try:
        return int(corpo) > time.time()
    except ValueError:
        return False
