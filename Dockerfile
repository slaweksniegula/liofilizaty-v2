# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile dla Liofilizaty Tracker API
#
# Budujemy obraz zawierający:
#   - Python 3.12 slim
#   - DejaVu Sans (do renderu polskich znaków w PDF)
#   - wszystkie zależności z requirements.txt
#   - kod aplikacji
#
# Wolumen /app/data trzyma:
#   - prices.db (baza SQLite)
#   - raporty/*.pdf (wygenerowane PDF-y)
#
# Dzięki temu update aplikacji nie kasuje historii cen.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# Zmienne środowiskowe które chcemy mieć w każdym stage
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/data

# DejaVu Sans — niezbędne do renderowania polskich znaków w PDF-ach.
# Bez tego PDF ma kwadraty zamiast ą ę ś ć.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalujemy zależności Pythonowe W OSOBNYM STAGE niż kod — dzięki temu
# zmiana w *.py nie wymusza ponownej instalacji pakietów.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Kod aplikacji
COPY . .

# Wolumen na dane — trzymamy tu bazę i raporty
RUN mkdir -p /app/data/raporty
VOLUME /app/data

# Port serwera HTTP
EXPOSE 8000

# Health check — Docker/Coolify będzie go używał do restart policy
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/ || exit 1

# Domyślny entrypoint: serwer HTTP na porcie 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
