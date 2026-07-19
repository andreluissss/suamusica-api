FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements_api.txt .
RUN pip install --no-cache-dir -r requirements_api.txt

# Copy app
COPY suamusica_api.py .
COPY base_scraper.py .
COPY scraper_artists.py .
COPY scraper_playlists.py .
COPY scraper_podcasts.py .

# Healthcheck
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:$PORT/health')" || exit 1

# Start
CMD uvicorn suamusica_api:app --host 0.0.0.0 --port ${PORT:-8000}