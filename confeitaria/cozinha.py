"""Consumidor: processa pedidos e recupera mensagens sem confirmacao."""
import argparse
import json
import os
import time

import redis

from .comum import GRUPO, agora, calcular_total, chaves, cliente, log, preparar

# Resultado e confirmacao ocorrem na mesma execucao atomica no Redis.
# HSETNX impede duas fichas para o mesmo pedido em caso de reentrega.
# Isto NAO promete execucao exatamente uma vez de efeitos externos.
FINALIZAR = """
local novo = redis.call('HSETNX', KEYS[2], ARGV[2], ARGV[3])
redis.call('XACK', KEYS[1], ARGV[1], ARGV[4])
return novo
"""


def processar(r, nome, mensagem_id, campos, tempo, recuperada):
    stream, resultados = chaves()
    pedido = {}
    try:
        pedido = json.loads(campos.get("json", ""))
        total = calcular_total(pedido)
        pedido_id = pedido["pedido_id"]
        log("RECUPERADO" if recuperada else "RECEBIDO", trabalhador=nome,
            mensagem_id=mensagem_id, pedido_id=pedido_id)
        time.sleep(tempo)  # Simula o tempo de preparar a ficha, sem efeito externo.
        resultado = {
            "pedido_id": pedido_id, "cliente": pedido["cliente"],
            "status": "CONCLUIDO", "total_centavos": total,
            "trabalhador": nome, "concluido_em": agora(),
        }
    except (ValueError, KeyError, TypeError) as exc:
        # Um erro de formato vira um resultado de rejeicao, sem ciclo infinito.
        pedido_id = (pedido.get("pedido_id") if isinstance(pedido, dict) else None)
        if not isinstance(pedido_id, str) or not pedido_id:
            pedido_id = "INVALIDO-" + mensagem_id
        resultado = {"pedido_id": pedido_id, "status": "REJEITADO",
                     "motivo": str(exc), "trabalhador": nome, "concluido_em": agora()}
    criado = r.eval(FINALIZAR, 2, stream, resultados, GRUPO, pedido_id,
                    json.dumps(resultado, ensure_ascii=False), mensagem_id)
    log("CONFIRMADO" if criado else "DUPLICATA_IGNORADA", trabalhador=nome,
        mensagem_id=mensagem_id, pedido_id=pedido_id,
        status=resultado["status"], total_centavos=resultado.get("total_centavos"))


def executar(nome, tempo=1.0, recuperar_ms=5000):
    r = cliente()
    stream, _ = chaves()
    cursor = "0-0"
    pronto = False
    try:
        while True:
            try:
                preparar(r)
                if not pronto:
                    log("PRONTO", trabalhador=nome, stream=stream, grupo=GRUPO,
                        recuperar_ms=recuperar_ms, tempo_s=tempo)
                    pronto = True
                # O Redis rastreia pendencias; a aplicacao solicita a recuperacao.
                resposta = r.xautoclaim(stream, GRUPO, nome,
                                       min_idle_time=recuperar_ms,
                                       start_id=cursor, count=1)
                cursor, recuperadas = resposta[0], resposta[1]
                for mensagem_id, campos in recuperadas:
                    processar(r, nome, mensagem_id, campos, tempo, True)
                novas = r.xreadgroup(GRUPO, nome, {stream: ">"}, count=1, block=300)
                for _, mensagens in novas:
                    for mensagem_id, campos in mensagens:
                        processar(r, nome, mensagem_id, campos, tempo, False)
            except (redis.ConnectionError, redis.TimeoutError):
                log("REDIS_INDISPONIVEL", trabalhador=nome, nova_tentativa_s=1)
                pronto = False
                time.sleep(1)
    except KeyboardInterrupt:
        log("ENCERRADO", trabalhador=nome)
    finally:
        r.close()


def main():
    parser = argparse.ArgumentParser(description="Trabalhador da cozinha")
    parser.add_argument("--nome", default=f"cozinha-{os.getpid()}")
    parser.add_argument("--tempo", type=float, default=1.0,
                        help="Segundos de processamento simulado por pedido")
    parser.add_argument("--recuperar-ms", type=int, default=5000,
                        help="Tempo sem confirmacao antes de tentar recuperar")
    args = parser.parse_args()
    if not 0 <= args.tempo <= 60:
        parser.error("--tempo deve estar entre 0 e 60 segundos.")
    if args.recuperar_ms < (args.tempo + 1) * 1000:
        parser.error("--recuperar-ms deve superar --tempo por pelo menos 1 segundo.")
    executar(args.nome, args.tempo, args.recuperar_ms)


if __name__ == "__main__":
    main()
