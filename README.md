# Rede de Testes Distribuída

## Nota: 20
Diogo Duarte (120482)

Thiago Vicente (121497)

## Visão Geral

Distributed CD Tester é um sistema baseado em Python projetado para distribuir e executar testes automatizados em múltiplos nós numa rede descentralizada. Utiliza Docker para conteinerização, `asyncio` para comunicação assíncrona e `pytest` para execução de testes. O sistema é tolerante a falhas, capaz de detectar falhas de nós, redistribuir tarefas e eleger nós de recuperação para garantir operação contínua.

## Principais Funcionalidades

- **Processamento Distribuído de Tarefas**: Divide módulos de teste de projetos submetidos e distribui-os entre nós.
- **Tolerância a Falhas**: Usa heartbeats para detectar falhas de nós, redistribui tarefas e elege nós de recuperação.
- **API REST**: Fornece endpoints para submeter projetos, consultar estados de avaliações e obter estatísticas da rede.
- **Implantação Conteinerizada**: Executa nós em contêineres isolados com Docker Compose.
- **Escalabilidade**: Suporta adição dinâmica de nós a uma rede existente.
- **Integração com GitHub**: Baixa projetos de teste diretamente de repositórios do GitHub.

## Estrutura do Projeto

```
├── README.md                # Documentação do projeto
├── requirements.txt         # Dependências Python
├── docker-compose.yml       # Orquestra múltiplos contêineres de nós
├── docker/                  # Arquivos relacionados ao Docker
│   ├── Dockerfile           # Definição da imagem Docker
│   ├── .dockerignore        # Arquivos a ignorar na construção do Docker
├── doc/                     # Documentação adicional
│   ├── Projecto CD 2025-3.pdf   # Documento principal do projeto
│   └── protocolo.pdf            # Detalhes do protocolo de rede
│   └── relatorio.pdf            # Detalhes do protocolo de rede
├── src/                     # Código-fonte
│   ├── api.py               # API REST baseada em Flask
│   ├── node.py              # Lógica central do nó
│   ├── managers/            # Gerenciadores de tarefas e cache
│   │   ├── BaseManager.py   # Classe base para gerenciadores
│   │   ├── CacheManager.py  # Gerenciamento de cache
│   │   ├── TaskManager.py   # Gerenciamento de tarefas
│   │   ├── README.md        # Documentação dos managers
│   ├── network/             # Comunicação de rede
│   │   ├── Network.py       # Abstração de rede
│   │   ├── message.py       # Tipos e estrutura de mensagens
│   │   ├── protocol.py      # Protocolo UDP assíncrono
│   │   ├── README.md        # Documentação da camada de rede
│   ├── utils/               # Funções utilitárias
│   │   ├── functions.py     # Manipulação de arquivos e GitHub
│   │   ├── module_finder.py # Descoberta de módulos de teste
│   │   ├── test_runner.py   # Execução de testes com pytest
```

## Requisitos

- **Docker**: Para executar nós em contêineres
- **Docker Compose**: Para orquestrar múltiplos nós
- **Dependências Python**: Listadas em `requirements.txt` (instaladas automaticamente no Docker)
- **Acesso à Internet**: Para baixar dependências e repositórios do GitHub

## Configuração

1. **Clonar o Repositório**:

   ```
    git clone \<URL\_DO\_REPOSITORIO>
    cd cd2025_proj_-120482_121497
   ```

2. **Configurar Variáveis de Ambiente**:

   ```
   export NIP=$(ip route get 1 | awk '{print $7}') # export local ip so docker can access it
   ```

3. **Construir a Imagem Docker**:

   ```
    docker compose build
   ```

4. **Iniciar a Rede**:

   - Usando Docker Compose:

   ```
    docker compose up -d nodeX # começar uma nova rede
   ```

Isso iniciará um nó (`nodeX`) com portas configuradas para comunicação UDP e API TCP.

5\. **Adicionar um Nó a uma Rede Existente**:

```bash
HOST=ip_de_um_no_qualquer:porta_do_mesmo_no docker compose up -d nodeX # adicionar um novo nó à rede
```

## Uso

### Submeter uma Avaliação

- **Via URL do GitHub**:

  ```
    curl -X POST http\://\<OUTSIDE\_IP>:\<API\_PORT>/evaluation&#x20;
    -H "Content-Type: application/json"&#x20;
    -d '{"urls": \["[https://github.com/user/repo](https://github.com/user/repo)"], "token": "\<GITHUB\_TOKEN>"}'
  ```

* **Via Arquivo ZIP**:
  ```bash
    curl -X POST http://<OUTSIDE_IP>:<API_PORT>/evaluation \
    -F "file=@/caminho/para/projeto.zip"
  ```

A resposta inclui um `eval_id` para rastrear a avaliação.

### Consultar Status de Avaliação

- **Avaliação específica**:

  ```bash
    curl http\://\<OUTSIDE\_IP>:\<API\_PORT>/evaluation/\<eval\_id>
  ```

* **Listar todas as avaliações**:
  ```bash
    curl http://<OUTSIDE_IP>:<API_PORT>/evaluation
  ```

### Consultar Estatísticas da Rede

```bash
curl http://<OUTSIDE_IP>:<API_PORT>/stats
```

### Consultar Topologia da Rede

```bash
curl http://<OUTSIDE_IP>:<API_PORT>/network
```

## Arquitetura

### Componentes Principais

- **Nó (`node.py`)**: Gerencia processamento de tarefas, comunicação, tolerância a falhas e interação com a API.
- **API Flask (`api.py`)**: Interface web para submissão de projetos e consultas.
- **Network (`Network.py`)**: Abstrai a comunicação UDP entre nós, gerenciando mensagens.
- **PytestRunner (`test_runner.py`)**: Executa testes de módulos usando `pytest` e parseia resultados.
- **Utils (`functions.py`, `module_finder.py`)**: Funções auxiliares para manipulação de arquivos e descoberta de módulos.

### Fluxo de Operação

1. **Inicialização**: Cada nó conecta-se à rede via `Network`.
2. **Submissão de Projeto**: Projeto enviado via API, dividido em módulos de teste.
3. **Distribuição de Tarefas**: Módulos são enfileirados e distribuídos entre nós.
4. **Execução de Testes**: Cada nó executa os módulos atribuídos e coleta resultados.
5. **Tolerância a Falhas**: Heartbeats monitoram nós; falhas disparam redistribuição e eleição de recuperação.
6. **Resultados**: Agregados e acessíveis via API.

## Tolerância a Falhas e Eleição de Recuperação

### Detecção de Falhas

Cada nó envia periodicamente mensagens de heartbeat para os demais. Se um nó deixa de receber heartbeats de outro por mais de 15 segundos, considera aquele nó como falho.

### Processo de Recuperação

1. O nó que detecta a falha identifica quais tarefas estavam sob responsabilidade do nó falho.
2. Inicia-se uma eleição entre os nós ativos para decidir quem assumirá essas tarefas.
3. Todos os nós anunciam sua candidatura. Após um breve período, o nó com menor ID é eleito.
4. O nó eleito assume as tarefas pendentes do nó falho e as redistribui para processamento.

Esse mecanismo garante que avaliações não sejam perdidas e que a rede continue operando mesmo em caso de falhas.

## Manutenção

- **Limpar Imagens Docker Não Utilizadas**:

  ```bash
   sudo docker images -f "dangling=true" -q | xargs -r sudo docker rmi
  ```

* **Acessar Logs**:
  ```bash
    docker logs <nome_do_container>
  ```

---

## Ilustração do Fluxo do Projeto

<div align="center">
  <h4>Exemplo visual do fluxo das mensagens durante vários cenários entre os quais falhas do coordenador ou do worker</h4>
  <img src="https://github.com/user-attachments/assets/388703f1-b046-4536-b263-42a6a68bc289" alt="GIF ilustrativo do processo de recuperação">
</div>

---

