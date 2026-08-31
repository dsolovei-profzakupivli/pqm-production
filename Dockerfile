FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=10000 \
    PQM_ENV=test_web \
    PQM_DATA_DIR=/var/data \
    PQM_ENABLE_BROWSER=0 \
    PQM_ENABLE_SCHEDULER=0 \
    PQM_ENABLE_NAZK_SCHEDULER=0 \
    PQM_BIDS_MODE=disabled \
    PQM_ENABLE_BIDS_UPDATE=0 \
    PQM_ENABLE_POWERBI=0 \
    PQM_ENABLE_GOOGLE=0 \
    PQM_TESSERACT_EXE=/usr/bin/tesseract \
    PQM_PDFTOPPM_EXE=/usr/bin/pdftoppm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl libreoffice nodejs npm poppler-utils \
       tesseract-ocr tesseract-ocr-ukr \
    && npm install --global pnpm@9 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY tools/prozorro_eds_adapter/package.json tools/prozorro_eds_adapter/pnpm-lock.yaml ./tools/prozorro_eds_adapter/
RUN cd tools/prozorro_eds_adapter && pnpm install --frozen-lockfile --prod

COPY . .

RUN mkdir -p /var/data

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1
CMD ["python", "server.py"]
