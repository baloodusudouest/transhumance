# syntax=docker/dockerfile:1
# ---------- Étape 1 : interface Svelte compilée ----------
FROM node:22-bookworm-slim AS interface
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN mkdir -p /app && npx vite build --outDir /app/static --emptyOutDir

# ---------- Étape 2 : dépendances Python en roues ----------
FROM python:3.12-slim-bookworm AS roues
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---------- Étape 3 : image d'exécution ----------
FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.title="transhumance" \
      org.opencontainers.image.description="Fait passer une bibliothèque externe d'Immich dans son stockage, en gardant personnes et albums" \
      org.opencontainers.image.source="https://github.com/baloodusudouest/transhumance"
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
COPY --from=roues /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
WORKDIR /app
COPY app ./app
COPY --from=interface /app/static ./app/static
ENV TZ=Europe/Paris PYTHONUNBUFFERED=1 TRANSHUMANCE_DATA=/data TRANSHUMANCE_PHOTOS=/photos
EXPOSE 8097
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8097/health')" || exit 1
# Tourne en root : il faut pouvoir supprimer, sur un clic, les fichiers d'origine du dossier des photos.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8097", "--proxy-headers"]
