import os
from pathlib import Path

SOLR_URL = os.environ.get(
    "CARF_SOLR_URL", "https://acordaos.economia.gov.br/solr/acordaos2/select"
)
USER_AGENT = os.environ.get(
    "CARF_USER_AGENT", "carf-intelligence/0.1 (pesquisa juridica; coleta com limite de taxa)"
)
DATA_DIR = Path(os.environ.get("CARF_DATA_DIR", "data"))
PAGE_SIZE = int(os.environ.get("CARF_PAGE_SIZE", "200"))
REQUEST_DELAY = float(os.environ.get("CARF_REQUEST_DELAY", "0.7"))

# Páginas do CARF vigiadas pelo monitor.
CARF_PAGES = (
    "https://www.gov.br/carf/pt-br/acesso-a-informacao/dados-abertos",
    "https://www.gov.br/carf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-1",
)

# Resultados com menos casos que isto não são exibidos por relator (evita perfilar pessoa
# a partir de amostra pequena).
MIN_SAMPLE_PER_RELATOR = 30
