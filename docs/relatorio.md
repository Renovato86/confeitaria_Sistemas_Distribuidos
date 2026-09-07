# Confeitaria distribuída
## Processamento de pedidos com Redis Streams

**Disciplina:** Sistemas Distribuídos

**Professor:** Dr. Leandro Alexandre Freitas

**Integrantes:** [preencher os nomes]

### Identificação e justificativa

**Plataforma:** Redis Streams. **Categoria:** streaming de eventos, utilizado como fila de trabalho. **Modelo de comunicação:** assíncrono, com um produtor e consumidores pertencentes ao mesmo grupo.

A escolha permite estudar o armazenamento de mensagens, a distribuição de tarefas e a recuperação de pedidos interrompidos. Redis Streams consta entre os exemplos do enunciado e permite uma aplicação pequena, com comportamento observável por logs e comandos de consulta.

### Aplicação implementada

O sistema representa uma confeitaria. O balcão cadastra um pedido com cliente, produtos e quantidades. A cozinha valida a mensagem, calcula o total e registra uma ficha digital para consulta. Há três produtos de demonstração: brigadeiro, beijinho e brownie. O tempo de preparação é simulado; a validação, o cálculo, a comunicação e o armazenamento dos resultados são executados pelo programa.

### Arquitetura

![Arquitetura da aplicação](arquitetura.png)

Cada caixa de aplicação representa um processo independente. O balcão conhece o endereço do Redis e o contrato da mensagem; não precisa conhecer o endereço ou o código da cozinha. Os dois trabalhadores compartilham o grupo `cozinha`. A consulta dos resultados também passa pelo Redis.

<!-- PAGEBREAK -->

## Implementação e preparação do ambiente

### Componentes e responsabilidades

| Componente | Responsabilidade |
| --- | --- |
| `balcao.py` | Cadastrar pedidos, publicar mensagens e consultar fichas |
| `cozinha.py` | Consumir, calcular, registrar resultado e confirmar |
| `compose.yaml` | Configurar o Redis com persistência em volume |

### Ambiente utilizado nas evidências

A execução de referência ocorreu em **07/09/2026**: Linux, Python **3.12.13**, Redis **6.2.14** e redis-py **5.2.1**. Redis, balcão e cozinhas foram processos separados, conectados por TCP local. No primeiro experimento, seus PIDs foram, respectivamente, 7, 11 e 12.

O pacote opcional `redislite` disponibilizou o binário real do Redis. A execução foi local, sem Docker. O caminho com containers foi preparado para reprodução, inclusive no Windows, mas não foi executado no ambiente de referência.

### Configuração principal

O endpoint padrão é `redis://127.0.0.1:6379/0`, com RESP sobre TCP. A demonstração local usa uma porta livre. Pedidos em JSON ficam no stream `confeitaria:pedidos`, grupo `cozinha`; fichas ficam no hash `confeitaria:resultados`. Cada teste automático usa um prefixo próprio.

A persistência utiliza `appendonly yes` e `appendfsync always`. Cada leitura entrega uma mensagem. A recuperação é solicitada após 5.000 ms sem confirmação. O processamento durou 0,2 segundo nos testes normais e 3 segundos na cozinha interrompida.

### Instalação e execução

No Windows, com Python e Docker Desktop instalados, abra o PowerShell na pasta do projeto e execute:

```text
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d
docker compose exec redis redis-cli ping
.\.venv\Scripts\python.exe demonstracao.py
```

A resposta `PONG` confirma o Redis acessível. O README traz os comandos em terminais separados. Em Linux, a execução integral usa `python demonstracao.py --local`, após instalar `requirements-local.txt` no ambiente Python.

<!-- PAGEBREAK -->

## Evidências de comunicação e concorrência

### Aplicação em funcionamento

Foram enviados dois pedidos antes de iniciar a cozinha. O Redis armazenou ambos, com zero resultados nesse momento. Após iniciar o consumidor, os dois pedidos foram processados, com totais de **R$ 11,00** e **R$ 14,00**. Ao final, havia dois resultados e nenhuma mensagem pendente de confirmação.

Trecho dos registros reais, com seleção de campos para facilitar a leitura. Os horários estão em UTC, em 07/09/2026:

```text
16:37:33.108 | PID 11 | ENVIADO
16:37:33.210 | PID 12 | RECEBIDO
16:37:33.410 | PID 12 | CONFIRMADO | total_centavos=1100
pedido_id: PED-a25888075bdc
mensagem_id: 1788799053108-0
```

Os três eventos acima se referem ao mesmo pedido e à mesma mensagem. A existência de PIDs distintos comprova que produtor e consumidor não são partes de um único processo. O envio antes da inicialização da cozinha demonstra o desacoplamento temporal.

**Origem:** `evidencias/01_comunicacao/balcao.log`, `cozinha-1.log`, `consulta.log` e `painel.log`, dentro da pasta desse experimento.

### Múltiplas instâncias

Foram iniciados dois trabalhadores e publicados oito pedidos. A distribuição observada foi:

| Trabalhador | PID | Pedidos concluídos |
| --- | --- | --- |
| cozinha-1 | 15 | 4 |
| cozinha-2 | 16 | 4 |
| Total | Dois processos | 8 |

Os trabalhadores competiram pelas mensagens do mesmo grupo. Cada pedido teve uma ficha final. A divisão em quatro pedidos para cada um foi o resultado dessa execução; não é uma garantia de distribuição perfeitamente igual. A ordem de conclusão também pode variar conforme o tempo de processamento.

O mecanismo responsável é o grupo de consumidores utilizado por `XREADGROUP`. Em outro desenho, grupos diferentes poderiam acompanhar o mesmo histórico de forma independente; isso não foi necessário nesta aplicação. [1]

**Origem:** `evidencias/02_concorrencia/` e o campo `concorrencia` de `evidencias/resumo.json`.

<!-- PAGEBREAK -->

## Experimentos de falha e recuperação

### Interrupção de um trabalhador

O processo `cozinha-falha`, PID 19, recebeu um pedido e foi encerrado deliberadamente com `SIGKILL` antes de registrar o resultado e confirmar a mensagem. A consulta ao Redis mostrou uma mensagem pendente, associada a esse consumidor, e nenhum resultado para o pedido.

O processo `cozinha-ativa`, PID 21, continuou processando. Ele concluiu um pedido novo enquanto o anterior aguardava recuperação. Depois de aproximadamente 5,26 segundos desde o recebimento inicial, recuperou o pedido interrompido. A ficha foi registrada e a pendência foi removida.

```text
16:37:35.405 | PID 19 | RECEBIDO
16:37:40.668 | PID 21 | RECUPERADO
16:37:40.868 | PID 21 | CONFIRMADO | total_centavos=1600
pedido_id: PED-167c6febc073
mensagem_id: 1788799055404-0
```

O identificador permaneceu igual: foi recuperada a mensagem original. Uma nova instância da cozinha também foi iniciada, com PID 23, e processou outro pedido. O experimento terminou com três resultados e zero pendências.

O Redis mantém o registro das entregas sem confirmação. A aplicação consulta esse registro com `XAUTOCLAIM` e define o tempo para a recuperação. Uma mensagem antiga não é uma prova absoluta de que o consumidor morreu: ele também pode estar lento. [2, 3]

**Origem:** `evidencias/03_falha/` e o campo `falha` do resumo. Os registros acima apresentam campos selecionados dos logs originais.

### Reentrega e persistência

Em outro teste, o mesmo pedido foi publicado duas vezes. Foram observadas duas mensagens e apenas uma ficha. O código registra o resultado com `HSETNX` e confirma a mensagem no mesmo script Lua. A segunda tentativa produziu `DUPLICATA_IGNORADA`. Essa proteção vale para a ficha armazenada; não constitui garantia geral de execução exatamente uma vez de efeitos externos. [4]

O Redis também foi encerrado com `SIGKILL` e reiniciado com o mesmo arquivo AOF. O pedido gravado antes da interrupção continuou disponível e foi processado depois. Um novo envio durante a parada retornou erro: ele não foi armazenado. O produtor não possui uma fila local para esse caso.

**Limites:** o teste demonstrou recuperação após interrupção de processos. Não foram testadas perda do disco, partições entre computadores nem troca automática para uma réplica. O AOF preservou o dado observado, mas o servidor único permaneceu indisponível enquanto estava parado. [5]

<!-- PAGEBREAK -->

## Respostas às questões de análise

### 1. Qual é o papel do middleware na solução?

Receber e armazenar os pedidos, entregá-los às cozinhas e manter o controle de confirmações e pendências. Isso permite que os programas cooperem sem estabelecer uma conexão direta entre balcão e cozinha.

### 2. Qual categoria melhor descreve a plataforma?

Streaming de eventos. Redis Streams mantém um histórico de mensagens com identificadores. Neste projeto, esse recurso é utilizado como uma fila de trabalho, com consumidores que dividem os pedidos de um mesmo grupo.

### 3. A comunicação é síncrona, assíncrona ou híbrida?

O fluxo de negócio é assíncrono: cadastrar o pedido não exige esperar sua conclusão. Cada comando entre o programa e o Redis tem uma resposta técnica, mas isso não torna o processamento do pedido uma chamada síncrona à cozinha.

### 4. Os componentes precisam conhecer a implementação dos outros?

Não. Eles compartilham o contrato da mensagem, o nome do stream e o endereço do Redis. A cozinha pode ser alterada sem exigir que o balcão conheça seu código, desde que esse contrato seja mantido.

### 5. Existe desacoplamento espacial, temporal ou ambos?

Ambos. Espacial: o balcão não conhece o endereço de cada cozinha. Temporal: um pedido pode ser publicado com a cozinha desligada e processado quando ela iniciar. Esse comportamento depende de o Redis estar disponível e preservar os dados necessários.

### 6. Quais detalhes de rede ou infraestrutura foram abstraídos?

O cliente redis-py implementa conexão e protocolo Redis; o servidor oferece armazenamento do stream, identificadores e estado do grupo. A aplicação ainda define o JSON, valida os dados, configura o endpoint e decide quando tentar recuperar uma mensagem. Não foi implementada descoberta automática.

### 7. Como a plataforma lida com concorrência?

O grupo de consumidores distribui as mensagens entre trabalhadores de nomes distintos. No teste, dois processos concluíram oito pedidos, quatro por processo. A concorrência aumenta a capacidade de processamento, mas a divisão exata e a ordem final não são garantidas.

<!-- PAGEBREAK -->

## Respostas às questões de análise — continuação

### 8. Como o sistema se comportou durante a falha?

O pedido do trabalhador interrompido ficou pendente e foi recuperado por outra cozinha. Um pedido novo foi processado durante a espera. Quando a falha atingiu o próprio Redis, o novo envio recebeu erro; após o reinício, o pedido anteriormente persistido foi encontrado.

### 9. Quais mecanismos contribuem para escalabilidade?

A adição de consumidores permite dividir o processamento dos pedidos. O stream absorve uma fila de trabalho quando a entrada supera temporariamente a capacidade das cozinhas. Neste protótipo, o Redis central e a memória disponível continuam limitando o crescimento.

### 10. Quais mecanismos contribuem para tolerância a falhas?

A lista de pendências, as confirmações explícitas, a recuperação por `XAUTOCLAIM`, a gravação AOF e a proteção da ficha contra duplicação. Parte do comportamento depende do código que invoca essas primitivas. Réplicas e failover não foram configurados.

### 11. Quais limitações ou desvantagens foram identificadas?

Dependência de um Redis único, uso de memória, histórico sem política de retenção e custo de gravar o AOF com sincronização frequente. Pausas longas podem provocar reentrega; o intervalo de recuperação precisa considerar o tempo normal de processamento. Autenticação e TLS não fazem parte do laboratório local.

### 12. Como seria a solução sem o middleware?

Seria necessário criar a comunicação por sockets ou outro transporte e acrescentar um serviço próprio para armazenar pedidos, controlar entregas e confirmações, distribuir tarefas e recuperar falhas. A lógica da confeitaria continuaria necessária, somada a esse trabalho de infraestrutura.

### 13. Em quais cenários reais a plataforma seria adequada?

Processamento de pedidos, geração de relatórios, notificações e outras tarefas que podem ser executadas em segundo plano. A adequação depende do volume, da política de retenção e das exigências de disponibilidade e recuperação da aplicação.

### 14. Em quais cenários não recomendaria esta solução?

Quando a operação exige resposta imediata do processamento, ausência de um intermediário central ou garantias rigorosas para efeitos externos, como cobranças. O protótipo também precisaria de outra arquitetura e configuração para alta disponibilidade ou um histórico muito maior que a memória planejada.

<!-- PAGEBREAK -->

## Síntese comparativa e conclusão

| Plataforma | Categoria | Modelo | Broker? | Persistência | Escalabilidade | Tolerância a falhas |
| --- | --- | --- | --- | --- | --- | --- |
| Redis Streams | Streaming de eventos | Assíncrono | Sim | AOF habilitado | Consumidores no mesmo grupo | Confirmação e recuperação de pendências |

### O que o middleware realizou para a aplicação?

O Redis forneceu mensagens com identificadores, armazenamento, controle de entregas, confirmações e suporte à recuperação. O cliente Python forneceu acesso ao protocolo. Sem essas ferramentas, seria necessário implementar esses mecanismos ou integrá-los por outras soluções.

A aplicação permaneceu responsável pelo catálogo, contrato JSON, validação, cálculo do total, consulta das fichas e política de recuperação. O script de finalização combina primitivas do Redis para evitar fichas duplicadas. Isso mostra que o middleware reduz o trabalho de infraestrutura, mas não elimina as decisões do desenvolvedor.

### Conclusão

A solução demonstrou comunicação entre processos independentes, distribuição de trabalho e recuperação de um pedido após a interrupção de seu consumidor. O mesmo identificador nos logs permitiu acompanhar todo o percurso da mensagem. O armazenamento antes da inicialização da cozinha evidenciou o desacoplamento temporal.

O experimento com o servidor destacou uma distinção: preservar dados em disco não mantém o serviço continuamente disponível. Redis Streams atendeu ao objetivo didático, com as limitações de um laboratório que utiliza um único servidor e processos em um mesmo computador.

### Código, instruções e evidências

O pacote `confeitaria-redis` reúne código, configuração, instruções, logs e roteiro de apresentação. Preencha os nomes dos integrantes antes da entrega.

### Referências

[1] Redis. [XREADGROUP: grupos de consumidores](https://redis.io/docs/latest/commands/xreadgroup/).

[2] Redis. [XACK: confirmação de mensagens](https://redis.io/docs/latest/commands/xack/).

[3] Redis. [XAUTOCLAIM: recuperação de pendências](https://redis.io/docs/latest/commands/xautoclaim/).

[4] Redis. [Execução de scripts Lua](https://redis.io/docs/latest/develop/programmability/eval-intro/).

[5] Redis. [Persistência RDB e AOF](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/).

[6] Redis. [XADD: publicação em streams](https://redis.io/docs/latest/commands/xadd/).

[7] Redis. [Cliente redis-py para Python](https://redis.io/docs/latest/develop/clients/redis-py/).

Documentação consultada em 07/09/2026. As conclusões experimentais derivam dos arquivos em `evidencias/`; os exemplos de uso futuro são análises a partir do comportamento implementado.
