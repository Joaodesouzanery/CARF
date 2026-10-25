#!/bin/sh
# Cópia criptografada dos dados (Parquet, estado, tokens). Uso: BACKUP_SENHA=... scripts/backup.sh [destino]
# Mantém os últimos 14. Restaurar: openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_SENHA -in ARQ | tar xz -C /
set -eu
destino="${1:-/var/backups/carf}"
: "${BACKUP_SENHA:?defina BACKUP_SENHA}"
mkdir -p "$destino"
arq="$destino/carf-$(date -u +%Y%m%d-%H%M).tar.gz.enc"
docker run --rm -v carf_carf-data:/data:ro alpine tar cz -C / --exclude=data/hf --exclude=data/painel.antigo data \
  | openssl enc -aes-256-cbc -pbkdf2 -pass env:BACKUP_SENHA -out "$arq"
ls -1t "$destino"/carf-*.enc | tail -n +15 | xargs -r rm -f
echo "ok: $arq"
