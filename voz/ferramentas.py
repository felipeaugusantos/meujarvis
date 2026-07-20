"""Ferramentas do Jarvis falado.

Sem isto o modelo responde de cabeça: perguntado sobre o clima, ele inventa
uma previsão plausível. Aqui ele passa a consultar as mesmas rotas que
alimentam o painel.

A escolha da ferramenta é feita por palavras-chave, não pelo próprio modelo.
Um 8B local erra muito ao emitir JSON de function-calling, e o custo do erro
seria alto: silêncio ou resposta inventada. Casar palavras é grosseiro, mas
acerta quase sempre nas perguntas que se faz a um assistente de casa — e
quando não casa nada, a conversa segue normalmente.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

import httpx

PAINEL = "http://127.0.0.1:8001"

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"]

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _sem_acento(texto: str) -> str:
    normal = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in normal if unicodedata.category(c) != "Mn")


def _tem(texto: str, *termos: str) -> bool:
    limpo = _sem_acento(texto)
    return any(re.search(rf"\b{t}", limpo) for t in termos)


def _buscar(caminho: str) -> dict | None:
    try:
        with httpx.Client(timeout=8) as cli:
            r = cli.get(f"{PAINEL}{caminho}")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError:
        return None


# ------------------------------------------------------------------ consultas


def clima() -> str:
    d = _buscar("/api/clima")
    if not d:
        return "FALHA: o painel não respondeu, então não há dado de clima."

    linhas = [
        f"Clima agora em {d['cidade']}: {d['temperatura']} graus, {d['descricao'].lower()}.",
        f"Máxima de hoje {d['maxima']}, mínima {d['minima']}. "
        f"Sensação {d['sensacao']}. Umidade {d['umidade']} por cento.",
    ]

    if d.get("proximos"):
        proximos = ", ".join(
            f"{p['data'][8:10]}/{p['data'][5:7]} máxima {p['max']} mínima {p['min']}"
            for p in d["proximos"]
        )
        linhas.append(f"Próximos dias: {proximos}.")

    # A umidade baixa é o dado que mais importa no inverno de Ribeirão.
    if d["umidade"] < 30:
        linhas.append("Atenção: umidade muito baixa.")

    return " ".join(linhas)


def tarefas() -> str:
    d = _buscar("/api/tarefas")
    if d is None:
        return "FALHA: o painel não respondeu, então não há lista de tarefas."

    pendentes = [t["texto"] for t in d["itens"] if not t["feita"]]
    feitas = [t["texto"] for t in d["itens"] if t["feita"]]

    if not d["itens"]:
        return "A lista de tarefas está vazia."

    partes = []
    if pendentes:
        partes.append(f"Pendentes ({len(pendentes)}): " + "; ".join(pendentes) + ".")
    else:
        partes.append("Nenhuma tarefa pendente.")
    if feitas:
        partes.append(f"Já concluídas: {len(feitas)}.")
    return " ".join(partes)


def anotar(texto: str) -> str:
    """Cria uma tarefa a partir do que foi falado."""
    limpo = re.sub(
        r"^(jarvis[,\s]*)?(por favor[,\s]*)?"
        r"(anota|anote|anotar|adiciona|adicione|adicionar|cria|crie|criar|"
        r"lembra|lembre|lembrar)"
        r"(\s+(uma\s+)?(tarefa|lembrete|nota|na lista|pra mim|para mim|que eu|de))*"
        r"[:,\s]*",
        "", texto.strip(), flags=re.IGNORECASE,
    ).strip()

    if not limpo:
        return "FALHA: não entendi o que anotar."

    try:
        with httpx.Client(timeout=8) as cli:
            r = cli.post(f"{PAINEL}/api/tarefas", json={"texto": limpo})
            r.raise_for_status()
    except httpx.HTTPError:
        return "FALHA: não consegui salvar a tarefa."

    return f'Tarefa criada com sucesso: "{limpo}". Confirme isso ao usuário.'


def noticias() -> str:
    d = _buscar("/api/noticias")
    if not d or not d.get("itens"):
        return "FALHA: não há notícias disponíveis agora."

    manchetes = "; ".join(f"{n['titulo']} ({n['fonte']})" for n in d["itens"][:5])
    return f"Manchetes mais recentes: {manchetes}."


def sistema() -> str:
    d = _buscar("/api/sistema")
    if not d:
        return "FALHA: sem telemetria da máquina."

    def pct(v):
        return "indisponível" if v is None else f"{round(v)} por cento"

    return (
        f"Estado da máquina: processador em {pct(d['cpu'])}, "
        f"memória em {pct(d['ram'])}, placa de vídeo em {pct(d['gpu'])}, "
        f"memória de vídeo em {pct(d['vram'])}. "
        f"Modelo de linguagem: {d.get('modelo', 'desconhecido')}."
    )


def data_hora() -> str:
    agora = datetime.now()
    return (
        f"Agora são {agora.hour} horas e {agora.minute} minutos, "
        f"{DIAS[agora.weekday()]}, {agora.day} de {MESES[agora.month - 1]} "
        f"de {agora.year}."
    )


# -------------------------------------------------------------------- escolha


def consultar(pergunta: str) -> str | None:
    """Devolve o dado real pertinente à pergunta, ou None se nenhuma serve.

    A ordem importa: 'anotar' vem antes de 'tarefas' porque "anota uma tarefa"
    casaria com as duas, e a intenção ali é escrever, não ler.
    """
    if _tem(pergunta, "anota", "anote", "adiciona", "adicione", "lembra de",
            "lembre de", "cria uma tarefa", "criar tarefa", "poe na lista",
            "coloca na lista"):
        return anotar(pergunta)

    if _tem(pergunta, "clima", "tempo", "temperatura", "chuva", "chover",
            "calor", "frio", "umidade", "previsao", "graus"):
        return clima()

    if _tem(pergunta, "tarefa", "afazer", "pendencia", "pendente",
            "lista de tarefas", "tenho que fazer", "preciso fazer"):
        return tarefas()

    if _tem(pergunta, "noticia", "manchete", "aconteceu", "jornal",
            "novidade", "acontecendo"):
        return noticias()

    if _tem(pergunta, "cpu", "processador", "memoria", "placa de video",
            "gpu", "maquina", "computador", "desempenho", "sistema"):
        return sistema()

    if _tem(pergunta, "que horas", "horario", "que dia", "data de hoje",
            "hoje e", "dia da semana"):
        return data_hora()

    return None
