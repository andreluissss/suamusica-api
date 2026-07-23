#!/bin/bash
set -e

echo "=== Entrypoint iniciado ==="

# Priority 1: YOUTUBE_COOKIES_BASE64 (variável de ambiente com cookies codificados)
if [ -n "$YOUTUBE_COOKIES_BASE64" ]; then
    echo "✓ YOUTUBE_COOKIES_BASE64 encontrada, decodificando..."
    echo "$YOUTUBE_COOKIES_BASE64" | base64 -d > /app/scraper/cookies.txt
    if [ -f /app/scraper/cookies.txt ] && [ -s /app/scraper/cookies.txt ]; then
        export YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt
        echo "✓ Cookies decodificados com sucesso ($(wc -l < /app/scraper/cookies.txt) linhas)"
    else
        echo "✗ Falha ao decodificar YOUTUBE_COOKIES_BASE64"
    fi
fi

# Priority 2: Render Secret File
if [ -f /etc/secrets/cookies.txt ]; then
    echo "✓ Render Secret File encontrado em /etc/secrets/cookies.txt"
    cp /etc/secrets/cookies.txt /app/scraper/cookies.txt
    export YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt
    echo "✓ Cookies copiado para /app/scraper/cookies.txt ($(wc -l < /app/scraper/cookies.txt) linhas)"
fi

# Verifica se o arquivo existe
if [ -f /app/scraper/cookies.txt ]; then
    echo "✓ /app/scraper/cookies.txt existe e será usado"
else
    echo "✗ Nenhum arquivo de cookies encontrado. O YouTube pode bloquear requisições."
fi

echo "YOUTUBE_COOKIES_FILE: '$YOUTUBE_COOKIES_FILE'"
echo "=== Entrypoint finalizado ==="
echo ""

# Inicia o servidor
exec python scraper/run_server.py --host 0.0.0.0 --port 5000
