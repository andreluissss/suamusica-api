#!/bin/bash
set -e

echo "=== Entrypoint iniciado ==="

# Converter cookies para formato Netscape usando Python
convert_cookies() {
    python3 << 'PYEOF'
import re, sys

with open('/app/scraper/cookies.txt', 'r') as f:
    content = f.read()

# Se já começa com Netscape, está ok
if content.startswith('# Netscape'):
    print('  ✓ Já está no formato Netscape')
    sys.exit(0)

# Tentar converter formato JSON (comum em extensões Export All Cookies)
if content.strip().startswith('{') or content.strip().startswith('['):
    import json
    try:
        data = json.loads(content)
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            items = []
    except:
        items = []
    with open('/app/scraper/cookies.txt', 'w') as f:
        f.write('# Netscape HTTP Cookie File\n')
        for c in items:
            domain = c.get('domain', c.get('Domain', '.youtube.com'))
            flag = 'TRUE' if domain.startswith('.') else 'FALSE'
            path = c.get('path', c.get('Path', '/'))
            secure = 'TRUE' if c.get('secure', c.get('Secure', False)) else 'FALSE'
            exp = str(int(float(c.get('expirationDate', c.get('Expires', '2147483647')))))
            name = c.get('name', c.get('Name', ''))
            value = c.get('value', c.get('Value', ''))
            if name and value:
                f.write(f'{domain}\t{flag}\t{path}\t{secure}\t{exp}\t{name}\t{value}\n')
    print('  ✓ Convertido formato JSON para Netscape')
    sys.exit(0)

# Tentar converter formato linhas simples (name=value)
if '=' in content and ('youtube' in content.lower() or '.youtube' in content):
    with open('/app/scraper/cookies.txt', 'w') as f:
        f.write('# Netscape HTTP Cookie File\n')
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                parts = line.split('=', 1)
                name = parts[0].strip()
                value = parts[1].strip().rstrip(';')
                if name and value:
                    f.write(f'.youtube.com\tTRUE\t/\tFALSE\t2147483647\t{name}\t{value}\n')
    print('  ✓ Convertido formato name=value para Netscape')
    sys.exit(0)

print('  ⚠ Formato não reconhecido, tentando usar como está')
PYEOF
    return $?
}

# Priority 1: YOUTUBE_COOKIES_BASE64
if [ -n "$YOUTUBE_COOKIES_BASE64" ]; then
    echo "✓ YOUTUBE_COOKIES_BASE64 encontrada, decodificando..."
    echo "$YOUTUBE_COOKIES_BASE64" | base64 -d > /app/scraper/cookies.txt
    if [ -f /app/scraper/cookies.txt ] && [ -s /app/scraper/cookies.txt ]; then
        export YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt
        echo "✓ Cookies decodificados ($(wc -l < /app/scraper/cookies.txt) linhas)"
        convert_cookies
    else
        echo "✗ Falha ao decodificar YOUTUBE_COOKIES_BASE64"
    fi
fi

# Priority 2: Render Secret File
if [ -f /etc/secrets/cookies.txt ]; then
    echo "✓ Render Secret File encontrado em /etc/secrets/cookies.txt"
    cp /etc/secrets/cookies.txt /app/scraper/cookies.txt
    export YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt
    echo "✓ Cookies copiado ($(wc -l < /app/scraper/cookies.txt) linhas)"
    convert_cookies
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
