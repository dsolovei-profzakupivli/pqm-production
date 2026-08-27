FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=10000 \
    PQM_DATA_DIR=/var/data \
    TESSERACT_EXE=/usr/bin/tesseract \
    PDFTOPPM_EXE=/usr/bin/pdftoppm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       tesseract-ocr \
       tesseract-ocr-ukr \
       tesseract-ocr-eng \
       poppler-utils \
       libreoffice-writer \
       fonts-liberation \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app/
RUN mkdir -p /var/data /app/data/protocols

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','10000')+'/api/health', timeout=4).read()"

CMD ["python", "server.py"]
