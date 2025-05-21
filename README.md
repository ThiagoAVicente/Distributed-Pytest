[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/o1T9cPjJ)

## TO RUN
```bash
export NIP=$(ip route get 1 | awk '{print $7}') # export local ip so docker can access it
docker-compose up -d nodeX # começar uma nova rede
HOST=ip_de_um_no_qualquer:porta_do_mesmo_no docker-compose up -d nodeX # adicionar um novo nó à rede
```


```bash

sudo docker images -f "dangling=true" -q | xargs -r sudo docker rmi
```

