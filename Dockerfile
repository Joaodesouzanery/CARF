# Imagem única: o servidor, a carga diária e os scripts do painel usam a mesma base.
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
RUN pip install --no-cache-dir ".[ner,ask,embed,serve,xlsx]" matplotlib pandas
ENV CARF_DATA_DIR=/data PYTHONUNBUFFERED=1 HF_HOME=/data/hf
RUN useradd -m carf && mkdir -p /data && chown carf /data
USER carf
VOLUME /data
ENTRYPOINT ["carf"]
CMD ["--help"]
