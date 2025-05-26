# Pasta `network/` — Comunicação P2P entre Nós

Esta pasta contém os módulos responsáveis pela comunicação entre os nós da Rede de Testes Distribuída. Os scripts aqui implementam o protocolo P2P, permitindo descoberta, troca de tarefas, monitoramento de falhas e eleição de nós de recuperação.

## Estrutura dos Arquivos

- **Network.py**  
  Camada de abstração principal para a comunicação de rede.  
  - Gerencia a lista de peers (outros nós conhecidos).
  - Envia e recebe mensagens de acordo com o protocolo P2P.
  - Implementa métodos para cada tipo de mensagem (heartbeat, tarefas, eleição, etc).
  - Responsável por conectar o nó à rede, adicionar/remover peers e distribuir tarefas.

- **message.py**  
  Define os tipos e a estrutura das mensagens trocadas entre os nós.
  - Enum `MessageType`: lista todos os comandos suportados (ex: `HEARTBEAT`, `TASK_SEND`, `RECOVERY_ELECTION`).
  - Classe `Message`: facilita a criação, serialização e desserialização das mensagens em formato JSON.

- **protocol.py**  
  Implementa o protocolo de transporte assíncrono sobre UDP.
  - Classe `CDProto`: métodos utilitários para serializar e desserializar mensagens com cabeçalho de tamanho fixo.
  - Classe `AsyncProtocol`: baseada em `asyncio.DatagramProtocol`, gerencia o envio e recebimento de mensagens UDP de forma não bloqueante.
  - Permite que cada nó envie e receba mensagens de/para múltiplos peers simultaneamente.

- **\_\_init\_\_.py**  
  Arquivo vazio para tornar o diretório um pacote Python.

## Como Funciona a Comunicação

1. **Inicialização:**  
   Cada nó cria uma instância de `Network`, que por sua vez inicializa o protocolo UDP (`AsyncProtocol`) e começa a escutar por mensagens.

2. **Descoberta e Conexão:**  
   - Um nó novo envia uma mensagem `CONNECT` para um peer conhecido.
   - Recebe uma resposta `CONNECT_REP` com informações da rede e peers.

3. **Troca de Mensagens:**  
   - Todas as mensagens seguem o formato definido em `message.py` e são serializadas em JSON.
   - O envio e recebimento é feito de forma assíncrona, permitindo alta escalabilidade.

4. **Distribuição de Tarefas:**  
   - Nós anunciam tarefas disponíveis (`TASK_ANNOUNCE`).
   - Nós ociosos solicitam tarefas (`TASK_REQUEST`).
   - Tarefas são enviadas (`TASK_SEND`) e resultados retornam (`TASK_RESULT`).

5. **Monitoramento de Falhas:**  
   - Heartbeats (`HEARTBEAT`) são enviados periodicamente.
   - A ausência de heartbeats indica falha de um nó, disparando o processo de eleição.

6. **Eleição de Recuperação:**  
   - Quando um nó falha, os demais iniciam uma eleição (`RECOVERY_ELECTION`) para decidir quem assume suas tarefas.
   - O nó eleito atualiza os peers via `EVALUATION_RESPONSIBILITY_UPDATE`.

## Exemplo de Fluxo

- Um nó detecta que outro nó parou de enviar heartbeats.
- Inicia uma eleição para assumir as tarefas do nó falho.
- O nó eleito redistribui as tarefas pendentes para a rede.

## Observações

- Toda a comunicação é feita via UDP, garantindo baixa latência.
- O protocolo é tolerante a falhas e suporta a entrada e saída dinâmica de nós.
- Para detalhes do protocolo, consulte o arquivo `protocolo.pdf` na raiz do projeto.

---

