"""Executa experimentos reais; guarda logs e verifica os resultados observados.

Padrao: conecta ao Redis do compose. --local: inicia binario real instalado.
Cada produtor/consumidor e um subprocesso; nao ha Redis simulado nem mocks.
"""
import argparse
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import redis

RAIZ = Path(__file__).resolve().parent
GRUPO = "cozinha"


def esperar(funcao, descricao, segundos=20):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        valor = funcao()
        if valor:
            return valor
        time.sleep(0.05)
    raise AssertionError(f"Tempo esgotado: {descricao}")


def eventos(path):
    if not path.exists():
        return []
    registros = []
    for linha in path.read_text(encoding="utf-8").splitlines():
        try:
            registros.append(json.loads(linha))
        except json.JSONDecodeError:
            pass  # Pode haver uma linha ainda sendo escrita pelo processo.
    return registros


class Ambiente:
    def __init__(self, r, url, pasta, nome):
        self.r, self.pasta = r, pasta / nome
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.prefixo = "demo_" + nome + "_" + uuid.uuid4().hex[:8]
        self.stream = self.prefixo + ":pedidos"
        self.resultados = self.prefixo + ":resultados"
        self.env = dict(os.environ, REDIS_URL=url, PREFIXO=self.prefixo,
                        PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.processos = []

    def trabalhador(self, nome, tempo=0.2):
        caminho = self.pasta / f"{nome}.log"
        f = caminho.open("w", encoding="utf-8")
        p = subprocess.Popen(
            [sys.executable, "-m", "confeitaria.cozinha", "--nome", nome,
             "--tempo", str(tempo), "--recuperar-ms", "5000"],
            cwd=RAIZ, env=self.env, stdout=f, stderr=subprocess.STDOUT)
        self.processos.append((p, f))
        esperar(lambda: any(e.get("evento") == "PRONTO" for e in eventos(caminho)),
                f"{nome} iniciar")
        return p, caminho

    def balcao(self, *args, arquivo="balcao.log", sucesso=True):
        cp = subprocess.run([sys.executable, "-m", "confeitaria.balcao", *args],
                            cwd=RAIZ, env=self.env, capture_output=True,
                            text=True, encoding="utf-8", timeout=15)
        with (self.pasta / arquivo).open("a", encoding="utf-8") as f:
            f.write(cp.stdout + cp.stderr)
        if sucesso:
            assert cp.returncode == 0, cp.stderr
        else:
            assert cp.returncode != 0, "Esperava erro do produtor"
        return [json.loads(l) for l in cp.stdout.splitlines() if l.startswith("{")]

    def aguardar_resultados(self, n):
        esperar(lambda: self.r.hlen(self.resultados) == n, f"{n} resultados")
        esperar(lambda: self.r.xpending(self.stream, GRUPO)["pending"] == 0,
                "confirmacoes")

    def ler_resultados(self):
        return [json.loads(v) for v in self.r.hvals(self.resultados)]

    def parar(self):
        for p, f in self.processos:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=3)
            f.close()


def binario_redis():
    existente = shutil.which("redis-server")
    if existente:
        return existente
    spec = importlib.util.find_spec("redislite")
    if spec and spec.origin:
        candidato = Path(spec.origin).parent / "bin" / "redis-server"
        if candidato.exists():
            return str(candidato)
    raise RuntimeError("Redis local nao encontrado. Use Docker ou instale requirements-local.txt.")


def executar(args):
    saida = Path(args.saida).resolve()
    saida.mkdir(parents=True, exist_ok=True)
    broker, broker_log, temporario = None, None, None
    ambientes = []
    resumo = {"data_utc": datetime.now(timezone.utc).isoformat(),
              "sistema": platform.system(), "python": platform.python_version(),
              "redis_py": redis.__version__, "experimentos": {}}
    r = None
    try:
        if args.local:
            temporario = tempfile.TemporaryDirectory(prefix="confeitaria-redis-")
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                porta = s.getsockname()[1]
            url = f"redis://127.0.0.1:{porta}/0"
            comando = [binario_redis(), "--bind", "127.0.0.1", "--port", str(porta),
                       "--dir", temporario.name, "--appendonly", "yes",
                       "--appendfsync", "always", "--save", ""]
            broker_log = (saida / "redis.log").open("w", encoding="utf-8")
            broker = subprocess.Popen(comando, stdout=broker_log, stderr=subprocess.STDOUT)
            resumo["redis_pid_inicial"] = broker.pid
        else:
            url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3,
                                socket_connect_timeout=1)

        def disponivel():
            try:
                return r.ping()
            except redis.RedisError:
                return False

        esperar(disponivel, "Redis responder PING")
        resumo["redis"] = r.info("server")["redis_version"]
        resumo["persistencia"] = r.config_get("append*")
        print(f'Redis {resumo["redis"]}: conexao real confirmada.', flush=True)

        def novo(nome):
            a = Ambiente(r, url, saida, nome)
            ambientes.append(a)
            return a

        a = novo("01_comunicacao")
        enviados = a.balcao("lote", "--quantidade", "2")
        assert r.xlen(a.stream) == 2 and r.hlen(a.resultados) == 0
        antes = {"pedidos_armazenados": 2, "resultados": 0, "consumidores": 0}
        p, log1 = a.trabalhador("cozinha-1")
        a.aguardar_resultados(2)
        assert sorted(v["total_centavos"] for v in a.ler_resultados()) == [1100, 1400]
        a.balcao("listar", arquivo="consulta.log")
        depois = a.balcao("painel", arquivo="painel.log")[0]
        resumo["experimentos"]["comunicacao"] = {
            "prefixo": a.prefixo, "antes": antes, "depois": depois,
            "enviados": enviados, "trabalhador_pid": p.pid, "aprovado": True}
        a.parar()
        print("1/5: pedidos enviados com cozinha desligada foram processados depois.", flush=True)

        a = novo("02_concorrencia")
        p1, _ = a.trabalhador("cozinha-1")
        p2, _ = a.trabalhador("cozinha-2")
        a.balcao("lote", "--quantidade", "8")
        a.aguardar_resultados(8)
        contagem = dict(Counter(v["trabalhador"] for v in a.ler_resultados()))
        assert set(contagem) == {"cozinha-1", "cozinha-2"}
        assert sum(contagem.values()) == 8
        resumo["experimentos"]["concorrencia"] = {
            "prefixo": a.prefixo, "distribuicao": contagem,
            "pids": [p1.pid, p2.pid], "resultados": 8, "aprovado": True}
        a.balcao("listar", arquivo="consulta.log")
        a.parar()
        print(f"2/5: dois trabalhadores dividiram 8 pedidos: {contagem}.", flush=True)

        a = novo("03_falha")
        falho, caminho_falho = a.trabalhador("cozinha-falha", tempo=3)
        enviado = a.balcao("novo", "--cliente", "Cliente Falha",
                           "--item", "brownie:2")[0]
        recebido = esperar(lambda: next((e for e in eventos(caminho_falho)
                                        if e.get("evento") == "RECEBIDO"), None),
                            "trabalhador receber pedido antes da falha")
        falho.kill()  # Interrupcao real do processo antes de gravar resultado/XACK.
        falho.wait(timeout=3)
        pendencia = r.xpending_range(a.stream, GRUPO, "-", "+", 10)
        assert len(pendencia) == 1 and r.hlen(a.resultados) == 0
        ativo, caminho_ativo = a.trabalhador("cozinha-ativa")
        novo_enviado = a.balcao("novo", "--cliente", "Cliente Durante Falha",
                               "--item", "brigadeiro:3")[0]
        a.aguardar_resultados(2)
        recuperado = next(e for e in eventos(caminho_ativo)
                          if e.get("evento") == "RECUPERADO")
        assert recuperado["mensagem_id"] == enviado["mensagem_id"]
        assert recuperado["pedido_id"] == enviado["pedido_id"]
        ev_ativo = eventos(caminho_ativo)
        t_novo = next(i for i, e in enumerate(ev_ativo)
                      if e.get("evento") == "CONFIRMADO"
                      and e.get("pedido_id") == novo_enviado["pedido_id"])
        t_recuperado = next(i for i, e in enumerate(ev_ativo)
                            if e.get("evento") == "RECUPERADO")
        assert t_novo < t_recuperado, "O trabalhador deve atender novos pedidos durante a falha"
        ativo.terminate()
        ativo.wait(timeout=3)
        reiniciado, _ = a.trabalhador("cozinha-reiniciada")
        a.balcao("novo", "--cliente", "Cliente Retorno", "--item", "beijinho:4")
        a.aguardar_resultados(3)
        assert any(v["trabalhador"] == "cozinha-reiniciada" for v in a.ler_resultados())
        resumo["experimentos"]["falha"] = {
            "prefixo": a.prefixo, "pid_interrompido": falho.pid,
            "pid_recuperacao": ativo.pid, "pid_reiniciado": reiniciado.pid,
            "recebido": recebido, "pendencias_apos_falha": pendencia,
            "recuperado": recuperado, "novo_pedido_processado_antes_da_recuperacao": True,
            "pendentes_ao_final": 0, "resultados": 3, "aprovado": True}
        a.balcao("listar", arquivo="consulta.log")
        a.parar()
        print("3/5: processo interrompido; mesmo pedido recuperado; cozinha reiniciada.", flush=True)

        a = novo("04_reentrega")
        _, caminho = a.trabalhador("cozinha-1")
        original = a.balcao("novo", "--cliente", "Cliente Reentrega", "--item", "brownie:1")[0]
        a.aguardar_resultados(1)
        registro = r.xrange(a.stream)[0][1]
        r.xadd(a.stream, registro)  # Mesmo pedido em uma segunda mensagem para testar idempotencia.
        esperar(lambda: any(e.get("evento") == "DUPLICATA_IGNORADA" for e in eventos(caminho)),
                "reentrega sem duplicar o resultado")
        assert r.hlen(a.resultados) == 1 and r.xlen(a.stream) == 2
        assert r.xpending(a.stream, GRUPO)["pending"] == 0
        a.balcao("novo", "--cliente", "Cliente Invalido", "--item", "brownie:0",
                  arquivo="validacao.log", sucesso=False)
        assert r.xlen(a.stream) == 2
        resumo["experimentos"]["reentrega"] = {
            "prefixo": a.prefixo, "pedido_id": original["pedido_id"],
            "mensagens": 2, "resultados": 1, "quantidade_zero_rejeitada": True,
            "aprovado": True}
        a.parar()
        print("4/5: reentrega gerou uma unica ficha; quantidade invalida foi rejeitada.", flush=True)

        if args.local:
            a = novo("05_redis")
            a.balcao("novo", "--cliente", "Cliente Persistencia", "--item", "brownie:2")
            broker.kill()
            broker.wait(timeout=3)
            a.balcao("novo", "--cliente", "Cliente Indisponibilidade", "--item", "brownie:1",
                      arquivo="indisponibilidade.log", sucesso=False)
            broker = subprocess.Popen(comando, stdout=broker_log, stderr=subprocess.STDOUT)
            esperar(disponivel, "Redis reiniciar com o mesmo AOF")
            assert r.xlen(a.stream) == 1
            a.trabalhador("cozinha-1")
            a.aguardar_resultados(1)
            resumo["experimentos"]["redis"] = {
                "prefixo": a.prefixo, "interrupcao": "SIGKILL do processo Redis",
                "pid_reiniciado": broker.pid, "pedido_anterior_preservado": True,
                "novo_envio_durante_parada_rejeitado": True, "resultados": 1,
                "aprovado": True}
            a.parar()
            print("5/5: Redis interrompido e reiniciado; AOF preservou o pedido anterior.", flush=True)
        else:
            resumo["experimentos"]["redis"] = {
                "executado": False,
                "motivo": "Servidor externo; o roteiro nao encerra um Redis que nao iniciou."}
            print("5/5: reinicio do Redis externo nao executado; veja roteiro manual no README.", flush=True)
        resumo["resultado"] = "APROVADO"
    except Exception as exc:
        resumo["resultado"] = "FALHOU"
        resumo["erro"] = str(exc)
        raise
    finally:
        for a in ambientes:
            a.parar()
        if r:
            r.close()
        if broker:
            if broker.poll() is None:
                broker.terminate()
                broker.wait(timeout=5)
        if broker_log:
            broker_log.close()
        if temporario:
            temporario.cleanup()
        (saida / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    print(f"APROVADO. Logs e resumo em: {saida}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="Iniciar Redis real local e testar reinicio")
    parser.add_argument("--saida", default="evidencias-novas")
    executar(parser.parse_args())
