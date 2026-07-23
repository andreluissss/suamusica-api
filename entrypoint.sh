#!/bin/bash
# Entrypoint que verifica se existe Secret File do Render para cookies do YouTube

# Se o Render Secret File foi configurado, copia para o local esperado
if [ -f /etc/secrets/cookies.txt ]; then
    echo "Render Secret File found: copying cookies.txt"
    cp /etc/secrets/cookies.txt /app/scraper/cookies.txt
    export YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt
fi

# Inicia o servidor
exec python scraper/run_server.py --host 0.0.0.0 --port 5000