"""Produtor e consulta: cadastrar pedidos, enviar lotes e consultar resultados."""
import argparse
import json
import sys
import uuid

import redis

from .comum import (CATALOGO, GRUPO, agora, chaves, cliente, dinheiro, log,
                    preparar, validar_pedido)


def enviar(r, nome, itens):
    pedido = validar_pedido({
        "versao": 1, "pedido_id": "PED-" + uuid.uuid4().hex[:12],
        "cliente": nome.strip(), "itens": itens, "criado_em": agora(),
    })
    stream, _ = chaves()
    mensagem_id = r.xadd(stream, {"json": json.dumps(pedido, ensure_ascii=False)})
    log("ENVIADO", mensagem_id=mensagem_id, **pedido)
    return mensagem_id, pedido


def ler_itens(valores):
    itens = []
    for valor in valores:
        try:
            produto, qtd = valor.split(":")
            itens.append({"produto": produto, "quantidade": int(qtd)})
        except ValueError as exc:
            raise ValueError("Use --item produto:quantidade; exemplo: brownie:2") from exc
    return itens


def painel(r):
    preparar(r)
    stream, resultados = chaves()
    grupo = next(g for g in r.xinfo_groups(stream) if g["name"] == GRUPO)
    dados = {
        "redis": r.info("server")["redis_version"],
        "stream": stream, "grupo": GRUPO,
        "mensagens_no_historico": r.xlen(stream),
        "pendentes_de_confirmacao": r.xpending(stream, GRUPO)["pending"],
        "resultados_registrados": r.hlen(resultados),
        "consumidores_cadastrados": grupo["consumers"],
    }
    # Consumidor cadastrado nao significa necessariamente processo ativo.
    log("PAINEL", **dados)
    return dados


def main():
    parser = argparse.ArgumentParser(description="Balcao da confeitaria")
    sub = parser.add_subparsers(dest="acao", required=True)
    sub.add_parser("catalogo", help="Ver os produtos e precos de demonstracao")
    novo = sub.add_parser("novo", help="Cadastrar um pedido")
    novo.add_argument("--cliente", required=True)
    novo.add_argument("--item", action="append", required=True)
    lote = sub.add_parser("lote", help="Enviar pedidos de demonstracao")
    lote.add_argument("--quantidade", type=int, default=6)
    sub.add_parser("listar", help="Consultar pedidos e resultados")
    sub.add_parser("painel", help="Consultar o middleware")
    args = parser.parse_args()
    if args.acao == "catalogo":
        for codigo, item in CATALOGO.items():
            print(f'{codigo}: {item["nome"]} - {dinheiro(item["preco_centavos"])}')
        return
    r = cliente()
    try:
        if args.acao == "novo":
            enviar(r, args.cliente, ler_itens(args.item))
        elif args.acao == "lote":
            if not 1 <= args.quantidade <= 100:
                raise ValueError("Escolha de 1 a 100 pedidos.")
            for n in range(args.quantidade):
                enviar(r, f"Cliente {n + 1}", [
                    {"produto": "brigadeiro", "quantidade": n % 3 + 1},
                    {"produto": "brownie", "quantidade": 1},
                ])
        elif args.acao == "listar":
            stream, resultados = chaves()
            for mensagem_id, campos in r.xrange(stream):
                pedido = json.loads(campos["json"])
                resultado = r.hget(resultados, pedido["pedido_id"])
                # Ausencia de resultado pode significar fila OU processamento.
                if resultado:
                    saida = json.loads(resultado)
                else:
                    saida = {"pedido_id": pedido["pedido_id"],
                             "cliente": pedido["cliente"], "status": "AGUARDANDO_RESULTADO"}
                log("CONSULTA", mensagem_id=mensagem_id, **saida)
        else:
            painel(r)
    except (redis.RedisError, ValueError, KeyError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        r.close()


if __name__ == "__main__":
    main()
