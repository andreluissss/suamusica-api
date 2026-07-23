#!/bin/bash
set -e

echo "=== Entrypoint iniciado ==="

# Debug: lista diretórios
echo "Conteúdo de /app/scraper/:"
ls -la /app/scraper/
echo ""

echo "Conteúdo de /etc/secrets/ (se existir):"
ls -la /etc/secrets/ 2>/dev/null || echo "  (diretório não existe)"
echo ""

# Variáveis de ambiente antes
echo "YOUTUBE_COOKIES_FILE antes: '$YOUTUBE_COOKIES_FILE'"
echo "YOUTUBE_COOKIES_FROM_BROWSER antes: '$YOUTUBE_COOKIES_FROM_BROWSER'"
echo ""

# Se o Render Secret File foi configurado, copia para o local esperado
if [ -f /etc/secrets/cookies.txt ]; then
    echo "✓ Render Secret File encontrado em /etc/secrets/cookies.txt"
    echo "Tamanho: $(wc -l < /etc/secrets/cookies.txt) linhas"
    cp /etc/secrets/cookies.txt /app/scraper/cookies.txt
    export YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt
    echo "✓ Cookies copiado para /app/scraper/cookies.txt"
else
    echo "✗ Render Secret File NÃO encontrado em /etc/secrets/cookies.txt"
    echo "  Verifique se você configurou o Secret File no Dashboard do Render"
fi

# Verifica se o arquivo existe agora
if [ -f /app/scraper/cookies.txt ]; then
    echo "✓ /app/scraper/cookies.txt existe"
    echo "Primeiras 3 linhas:"
    head -3 /app/scraper/cookies.txt
    echo "Total de linhas: $(wc -l < /app/scraper/cookies.txt)"
else
    echo "✗ /app/scraper/cookies.txt NÃO existe"
fi

echo ""
echo "YOUTUBE_COOKIES_FILE depois: '$YOUTUBE_COOKIES_FILE'"
echo "=== Entrypoint finalizado ==="
echo ""

# Inicia o servidor
exec python scraper/run_server.py --host 0.0.0.0 --port 5000
