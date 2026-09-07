# Roteiro de apresentação - aproximadamente 6 minutos

## 1. Apresente a ideia

“A aplicação representa uma confeitaria. O balcão cadastra pedidos e a cozinha processa as fichas. Escolhemos Redis Streams, da categoria de streaming de eventos, usado aqui para distribuir tarefas de forma assíncrona.”

Explique o exemplo: dez brigadeiros e dois brownies formam um pedido de R$ 46,00. O programa valida os itens, calcula o total e guarda o resultado para consulta.

## 2. Mostre a arquitetura

Abra `docs/arquitetura.png`.

“Os programas não se chamam diretamente. Todos se conectam ao Redis. O balcão publica o pedido e uma das cozinhas recebe a mensagem. Depois do processamento, o resultado é registrado e a mensagem é confirmada.”

Redis é o middleware; Python é a linguagem; redis-py é o cliente que permite ao código conversar com o Redis. Docker é uma forma de executar o servidor.

## 3. Demonstre a comunicação

Com o Redis ativo, envie um pedido com as cozinhas paradas. Mostre que há pedido aguardando resultado. Inicie uma cozinha e acompanhe `RECEBIDO` e `CONFIRMADO`. Consulte a ficha final.

“O balcão não precisou esperar a cozinha estar ligada. Isso é desacoplamento temporal.”

## 4. Demonstre a concorrência

Abra uma segunda cozinha, com nome diferente, e envie oito pedidos. Mostre as mensagens nos dois terminais.

“As cozinhas pertencem ao mesmo grupo. Elas competem pelos pedidos. O Redis distribui o trabalho; o objetivo não é entregar uma cópia de cada pedido a todas as cozinhas. A divisão pode variar a cada execução.”

## 5. Demonstre a falha

Siga o [experimento manual de falha do trabalhador](guia-tecnico.md#experimento-manual-de-falha-do-trabalhador). Pare a cozinha lenta depois de `RECEBIDO` e antes de `CONFIRMADO`. Mostre a pendência e inicie outra cozinha. Compare os identificadores no evento `RECUPERADO`.

“O Redis registrou que a mensagem estava pendente. O código da outra cozinha pediu sua recuperação após cinco segundos sem confirmação. Quando o resultado foi salvo, a aplicação confirmou a entrega.”

O roteiro automático `demonstracao.py` também executa essa falha, interrompendo um processo real.

## 6. Conclua

“Sem o middleware, precisaríamos construir o protocolo entre os programas, armazenar mensagens, controlar quais já foram processadas e programar mecanismos de recuperação. O Redis oferece essas primitivas. Nossa aplicação continua responsável pelo catálogo, pela validação, pelo cálculo do total e pela política de quando recuperar um pedido.”

“A solução tolera a interrupção de um trabalhador, mas ainda depende de um Redis central. Persistência em disco não é a mesma coisa que alta disponibilidade.”

## Perguntas que o professor pode fazer

**O que vocês implementaram além de enviar uma mensagem?** Cadastro com itens e quantidades, validação, total do pedido, ficha final, consulta e recuperação de pedidos interrompidos.

**A comunicação é síncrona ou assíncrona?** O fluxo de negócio é assíncrono: cadastrar não espera o processamento. Cada comando enviado ao Redis tem sua própria resposta técnica.

**O que significa ACK?** A confirmação de que aquela mensagem foi tratada pelo consumidor. Aqui ela acontece junto com o registro do resultado.

**O Redis descobre sozinho que a cozinha caiu?** Ele acompanha as mensagens entregues e não confirmadas. Nosso código usa o tempo de pendência para pedir a recuperação; isso não é uma prova absoluta de que o processo morreu.

**A mesma mensagem nunca pode aparecer de novo?** Pode haver reentrega. Por isso o identificador do pedido impede a criação de uma segunda ficha. Não prometemos execução exatamente uma vez de qualquer efeito externo.

**O que é stream?** Um histórico de mensagens com identificadores. O grupo mantém o controle do que foi entregue e do que ainda precisa de confirmação.

**Um único computador pode demonstrar distribuição?** Sim, conforme o enunciado: são processos independentes que se comunicam por rede. Aqui usamos TCP local; o experimento não testa falhas entre computadores físicos diferentes.
