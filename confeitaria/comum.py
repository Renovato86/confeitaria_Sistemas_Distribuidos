"""Contrato de mensagens e acesso ao middleware, compartilhados pelos processos."""
import json
import os
import re
from datetime import datetime, timezone

import redis

CATALOGO = {
    "brigadeiro": {"nome": "Brigadeiro", "preco_centavos": 300},
    "beijinho": {"nome": "Beijinho", "preco_centavos": 300},
    "brownie": {"nome": "Brownie", "preco_centavos": 800},
}
GRUPO = "cozinha"


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log(evento, **dados):
    print(json.dumps({"hora_utc": agora(), "pid": os.getpid(),
                      "evento": evento, **dados}, ensure_ascii=False), flush=True)


def cliente():
    return redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True, socket_connect_timeout=3, socket_timeout=5,
    )


def chaves():
    prefixo = os.getenv("PREFIXO", "confeitaria")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", prefixo):
        raise ValueError("PREFIXO deve conter apenas letras, numeros, _ ou -.")
    return f"{prefixo}:pedidos", f"{prefixo}:resultados"


def preparar(r):
    stream, _ = chaves()
    try:
        # 0 inclui pedidos enviados antes de existir um consumidor.
        r.xgroup_create(stream, GRUPO, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if not str(exc).startswith("BUSYGROUP"):
            raise


def validar_pedido(pedido):
    if not isinstance(pedido, dict) or pedido.get("versao") != 1:
        raise ValueError("Mensagem deve ser um pedido de versao 1.")
    if not isinstance(pedido.get("pedido_id"), str) or not pedido["pedido_id"]:
        raise ValueError("Pedido sem identificador.")
    if not isinstance(pedido.get("cliente"), str) or not pedido["cliente"].strip():
        raise ValueError("Informe o cliente.")
    itens = pedido.get("itens")
    if not isinstance(itens, list) or not itens:
        raise ValueError("Informe pelo menos um item.")
    for item in itens:
        if not isinstance(item, dict) or item.get("produto") not in CATALOGO:
            raise ValueError("Produto fora do catalogo.")
        qtd = item.get("quantidade")
        if type(qtd) is not int or not 1 <= qtd <= 100:
            raise ValueError("Quantidade deve ser um inteiro entre 1 e 100.")
    return pedido


def calcular_total(pedido):
    validar_pedido(pedido)
    # Inteiros evitam erros de arredondamento em valores monetarios.
    return sum(CATALOGO[i["produto"]]["preco_centavos"] * i["quantidade"]
               for i in pedido["itens"])


def dinheiro(centavos):
    return f"R$ {centavos // 100},{centavos % 100:02d}"
