# Colocar no ar em servidor próprio

Uma máquina Linux com Docker roda tudo: a API e o painel, o HTTPS (Caddy) e a atualização diária.

## O que contratar
- VPS com **Ubuntu 22.04 ou mais novo, 4 GB de RAM, 2 vCPUs, 60 GB de disco**. A primeira carga e a
  vetorização usam bastante CPU (algumas horas); depois o consumo é baixo.
- Um **domínio** (ou subdomínio) apontando o registro A para o IP da VPS. Sem domínio, o painel só abre
  por IP, sem HTTPS: não use assim com clientes.
- Portas 80 e 443 liberadas.

## Passo a passo
```bash
# 1) Docker (Ubuntu)
curl -fsSL https://get.docker.com | sh

# 2) Código
git clone https://github.com/joaodesouzanery/carf && cd carf
git checkout claude/vibrant-archimedes-w968lm
cp deploy/.env.example .env && nano .env        # DOMINIO=carf.seudominio.com.br

# 3) Subir
docker compose up -d --build

# 4) Primeira carga (dura algumas horas; é retomável, pode reexecutar)
docker compose run --rm app sync --ano-min 2018 --leve --workers 3
docker compose run --rm app gerenciais atualizar --workers 2
docker compose run --rm app enriquecer
docker compose run --rm app embed
docker compose run --rm --entrypoint python app /app/scripts/painel/exportar.py /data /data/painel --ano-min 2018
docker compose run --rm --entrypoint python app /app/scripts/painel/prontas.py /data /data/painel
docker compose run --rm --entrypoint cp app /app/scripts/painel/painel.html /data/painel/index.html

# 5) Um token por escritório (aparece uma vez; no servidor fica só o hash)
docker compose run --rm app serve --novo-token "Martinelli Advogados"
docker compose restart app
```
A aba "Revisão LGPD" precisa da amostra de revisão (`revisao.json`), que usa texto integral e por isso é
gerada à parte: `carf review amostra --n 100`, depois `scripts/painel/exportar.py ... --revisao ARQ.md` numa pasta
temporária e copie o `revisao.json` para `/data/painel/`. Sem ele a aba fica vazia, o resto funciona.

Abra `https://SEU-DOMINIO/`, marque "Buscar por significado" e cole o token.

Redes: o contêiner precisa alcançar `acordaos.economia.gov.br`, `www.gov.br`, `carf.economia.gov.br` e,
na primeira vetorização, `huggingface.co`, `cas-server.xethub.hf.co` e `us.aws.cdn.hf.co`.

## Rotina diária
O serviço `agendador` roda sozinho às 07h UTC: `carf check` → carga incremental → dados oficiais →
`enriquecer` → `embed` → painel novo, trocado de uma vez. Se algo falha, mantém o painel anterior e
tenta no dia seguinte. Acompanhe com `docker compose logs -f agendador`.

## Sigilo das consultas
- A busca vai por `POST` (o texto não aparece em URL). O Caddy está com `log output discard` e o
  servidor roda sem access log; nada guarda o texto pesquisado.
- Não ligue logs de proxy externo (Cloudflare, load balancer) com corpo de requisição.
- Token por escritório, limite de 60 consultas por minuto por token. Para revogar, apague a linha do
  escritório em `tokens.json` dentro do volume e reinicie `app`.

## Backup
```bash
sudo BACKUP_SENHA='uma-senha-longa' scripts/backup.sh          # cópia criptografada, guarda as 14 últimas
echo '0 3 * * * root BACKUP_SENHA=... /caminho/scripts/backup.sh' | sudo tee /etc/cron.d/carf-backup
```
Guarde a senha fora do servidor. Sem ela o backup não abre.

## Atualizar o código
`git pull && docker compose up -d --build`. Os dados ficam no volume `carf_carf-data`.

## Checagens
- `curl -s https://SEU-DOMINIO/api/saude` → `{"ok":true}`
- Sem token, `POST /api/buscar` responde 401.
- `docker compose ps`: `app` deve estar `healthy`.
