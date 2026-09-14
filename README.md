# Confeitaria distribuída com Redis Streams (Python)

Sistema de pedidos de uma confeitaria desenvolvido em Python, utilizando Redis Streams como middleware de comunicação. O balcão cadastra os pedidos, as cozinhas processam as fichas em programas separados e o resultado fica disponível para consulta.

Trabalho desenvolvido para a disciplina de Sistemas Distribuídos.

## Aviso importante

A aplicação funciona pelo terminal e representa uma confeitaria fictícia. A configuração fornecida executa o Redis e os programas no mesmo computador, usando o endereço local `127.0.0.1`. O Redis precisa estar ligado para enviar e processar pedidos.

Os testes registrados foram executados em Linux. As instruções para Windows com Docker estão preparadas para reprodução, mas ainda precisam ser verificadas nesse ambiente.

## Sobre o projeto

O balcão permite consultar o catálogo, cadastrar pedidos de brigadeiros, beijinhos e brownies e acompanhar os resultados. Cada pedido informa o cliente, os produtos e suas quantidades.

Cada cozinha é um processo independente. Ela recebe um pedido pelo Redis, confere os itens, calcula o total e registra uma ficha de conclusão. É possível executar duas cozinhas ao mesmo tempo para dividir o atendimento. Se uma delas parar antes de confirmar um pedido, outra pode recuperá-lo.

Os eventos de envio, recebimento e conclusão aparecem no terminal. A demonstração automática também salva os registros em arquivos para análise.

A documentação completa está separada neste [relatório em texto](docs/relatorio.md) e um [guia técnico com os experimentos](docs/guia-tecnico.md).

## Pré-requisitos

- [Python](https://www.python.org/downloads/) instalado. A versão utilizada nos testes foi a **3.12**.
- **Windows:** [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) instalado e aberto, com o mecanismo de containers Linux iniciado.
- **Linux:** Docker Engine e o plugin Docker Compose instalados, com o serviço Docker em execução.
- Conexão com a internet na primeira instalação, para baixar as dependências e a imagem do Redis.

O Redis será instalado pelo Docker usando a configuração incluída no projeto. O Git é opcional: também é possível baixar os arquivos em ZIP.

## Instalação

### 1. Baixar o projeto

Na página deste repositório, clique em **Code > Download ZIP** e extraia o arquivo. Abra o terminal dentro da pasta que contém o `README.md` e o `compose.yaml`.

Se preferir usar Git:

```bash
git clone https://github.com/Renovato86/confeitaria_Sistemas_Distribu-dos.git
cd confeitaria_Sistemas_Distribu-dos
```

### 2. Instalar as dependências

No **Windows**, abra o PowerShell na pasta do projeto e execute:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

No **Linux**:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

### 3. Iniciar o Redis

Com o Docker em execução, rode:

```bash
docker compose up -d
docker compose exec redis redis-cli ping
```

Na primeira vez, aguarde o download da imagem. A resposta `PONG` indica que o Redis está pronto. Se ainda não responder, aguarde alguns segundos e repita o segundo comando.

### 4. Executar a aplicação

Abra **três terminais na pasta do projeto**. Os comandos abaixo são para o PowerShell do Windows. No Linux, substitua `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

**Terminal 1 — primeira cozinha:**

```powershell
.\.venv\Scripts\python.exe -m confeitaria.cozinha --nome cozinha-1
```

**Terminal 2 — segunda cozinha:**

```powershell
.\.venv\Scripts\python.exe -m confeitaria.cozinha --nome cozinha-2
```

**Terminal 3 — balcão:** consulte o catálogo e envie um pedido.

```powershell
.\.venv\Scripts\python.exe -m confeitaria.balcao catalogo
.\.venv\Scripts\python.exe -m confeitaria.balcao novo --cliente Ana --item brigadeiro:10 --item brownie:2
```

Uma das cozinhas receberá o pedido. Aguarde o evento `CONFIRMADO` e consulte o resultado no terminal do balcão:

```powershell
.\.venv\Scripts\python.exe -m confeitaria.balcao listar
```

O pedido de exemplo totaliza **R$ 46,00**. Nos registros, o valor aparece em centavos: `4600`.

Para enviar vários pedidos e acompanhar a divisão entre as cozinhas:

```powershell
.\.venv\Scripts\python.exe -m confeitaria.balcao lote --quantidade 8
.\.venv\Scripts\python.exe -m confeitaria.balcao painel
```

### 5. Executar a demonstração automática

Com o Redis ativo, execute no Windows:

```powershell
.\.venv\Scripts\python.exe demonstracao.py
```

No Linux:

```bash
.venv/bin/python demonstracao.py
```

O roteiro inicia seus próprios processos, verifica comunicação, concorrência, falha de uma cozinha e reentrega de pedidos e salva os logs em `evidencias-novas/`. Com Redis externo, como o do Docker, o teste de interrupção do servidor deve seguir o [roteiro manual do guia técnico](docs/guia-tecnico.md#experimento-manual-de-falha-do-redis).

### 6. Encerrar

Pressione **Ctrl+C** nos terminais das cozinhas. Depois encerre o Redis:

```bash
docker compose down
```

Os dados permanecem no volume do Docker para a próxima execução.
