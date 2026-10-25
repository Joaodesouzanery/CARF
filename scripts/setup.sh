#!/usr/bin/env bash
# Prepara o ambiente (Python 3.12 + dependências com as versões fixadas do NER).
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || pip install --quiet uv
uv venv --python 3.12 .venv
# shellcheck disable=SC1091
. .venv/bin/activate
uv pip install -e ".[ner,ask,embed,dev]"
python -c "import spacy; spacy.load('pt_core_news_lg'); print('NER ok')"
echo "Pronto. Use: . .venv/bin/activate && carf --help"
