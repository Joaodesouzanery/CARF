# Para rodar a carga e as consultas fora do ambiente de desenvolvimento (VPS, máquina do escritório).
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[ner,ask,embed]"
ENV CARF_DATA_DIR=/data
VOLUME /data
ENTRYPOINT ["carf"]
CMD ["--help"]
