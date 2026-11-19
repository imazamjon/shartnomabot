# Railway uchun: PDF (LibreOffice), OCR (Tesseract) va shriftlar bilan.
FROM python:3.14-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Tashkent \
    LANG=C.UTF-8 \
    SOFFICE_PATH=/usr/bin/soffice

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui \
      poppler-utils \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-rus tesseract-ocr-uzb \
      fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-dejavu-core \
      tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Tayyor fayllar volume ichida saqlansin (Railway volume -> /app/data).
RUN rm -rf contracts && ln -s data/contracts contracts \
 && soffice --version

CMD ["python3", "bot.py"]
