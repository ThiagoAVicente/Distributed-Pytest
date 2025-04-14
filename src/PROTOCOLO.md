# PROTOCOLO

## formato:
|size | mssg(json)|

## cmds:
### *IM_NEW*
menssagem enviada por novos nós ao nó central de forma a conhecer a rede

### *LIVECHECK*
menssagem enviada periodicamente por um nó aos outros para informar que ele está ativo

### *FREE*
menssagem enviada periodicamente por todos os nós que estejam livres ( sem trabalho a fazer )

### *WORKING* 
menssagem enviada periodicamente por todos os nós que estão a realizar uma tarefa 

### *RESULT*
menssagem enviada por um nó quando este acaba de realizar uma tarefa.

### *RESULT_ACK*
menssagem envaida pelo nó central a indicar que o resultado foi recebido

### *ELECTION*
menssagem enviada por um nó quando este não tem informação do nó central

### *ELECTION_REP*
menssagem enviada pelos nós a indicar o seu id para poder eleger um novo nó central

### *COORDINATOR*
menssagem enviada pelo nó que iniciou o processo de eleição com a informação de quem 
é o novo coordenador

### *EVALUATION*
menssagem enviada pela web api a enviar um novo projeto

### *EVALUATION_ACK*
...

### *STAT*
...

### *STAT_REP*
...

### *NETWORK*
...

### *NETWORK_REP*
...