#!/bin/sh
# Roda a atualização uma vez por dia (HORA_UTC). Cada etapa só avança se a anterior deu certo.
# Saída 10 de `carf check` = há novidade no índice; 0 = nada a fazer (o boletim sai de qualquer forma na segunda).
set -u
export CARF_DATA_DIR="${CARF_DATA_DIR:-/data}"
log() { echo "[$(date -u +%FT%TZ)] $*"; }

atualizar() {
  carf check --paginas
  rc=$?
  if [ "$rc" -eq 10 ] || [ ! -d "$CARF_DATA_DIR/painel" ]; then
    log "novidade no índice, atualizando"
    carf sync --ano-min "${ANO_MIN:-2018}" --leve --incremental --workers 2 || return 1
    carf gerenciais atualizar --workers 2 || log "dados oficiais: falhou (segue)"
    carf enriquecer || return 1
    carf embed || return 1
    mkdir -p "$CARF_DATA_DIR/painel"
    python /app/scripts/painel/exportar.py "$CARF_DATA_DIR" "$CARF_DATA_DIR/painel.novo" --ano-min "${ANO_MIN:-2018}" || return 1
    python /app/scripts/painel/prontas.py "$CARF_DATA_DIR" "$CARF_DATA_DIR/painel.novo" || log "pesquisas prontas: falhou (segue)"
    cp /app/scripts/painel/painel.html "$CARF_DATA_DIR/painel.novo/index.html"
    rm -rf "$CARF_DATA_DIR/painel.antigo"
    [ -d "$CARF_DATA_DIR/painel" ] && mv "$CARF_DATA_DIR/painel" "$CARF_DATA_DIR/painel.antigo"
    mv "$CARF_DATA_DIR/painel.novo" "$CARF_DATA_DIR/painel"
    log "painel atualizado"
  else
    log "sem novidades"
  fi
}

while true; do
  if [ "$(date -u +%H)" = "${HORA_UTC:-07}" ]; then
    atualizar || log "atualização falhou; tentará amanhã"
    sleep 3600
  fi
  sleep 300
done
