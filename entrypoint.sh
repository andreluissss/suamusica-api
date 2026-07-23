#!/bin/bash
set -e

echo "=== Entrypoint iniciado v2.3 - Audio format fix ==="

# Atualiza yt-dlp para a versão mais recente
echo "✓ Verificando versão do yt-dlp..."
pip install --upgrade yt-dlp 2>&1 | tail -1
echo ""

# Converter cookies para formato Netscape usando Python
convert_cookies() {
    python3 << 'PYEOF'
import re, sys

with open('/app/scraper/cookies.txt', 'r') as f:
    content = f.read()

# Se já começa com Netscape, verifica se está bem formatado
if content.startswith('# Netscape'):
    # Verifica se há pelo menos uma linha com 7 campos tab-separados
    lines = content.strip().split('\n')
    valid_lines = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) == 7:
            valid_lines += 1
    if valid_lines > 0:
        print(f'  ✓ Já está no formato Netscape ({valid_lines} cookies válidos)')
        sys.exit(0)
    else:
        print('  ⚠ Arquivo começa com Netscape mas sem cookies válidos, tentando reparar...')

# Reescrever o arquivo em formato Netscape estrito
# Remove linhas que não são cookies válidos
with open('/app/scraper/cookies.txt', 'r') as f:
    raw_lines = f.readlines()

with open('/app/scraper/cookies.txt', 'w') as f:
    f.write('# Netscape HTTP Cookie File\n')
    f.write('# https://curl.haxx.se/rfc/cookie_spec.html\n')
    f.write('# This is a generated file! Do not edit.\n')
    f.write('#\n')
    
    count = 0
    for line in raw_lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Tenta parsear como Netscape (tab-separated)
        parts = line.split('\t')
        if len(parts) == 7:
            domain, flag, path, secure, exp, name, value = parts
            # Valida campos básicos
            if domain and name and value:
                f.write(f'{domain}\t{flag}\t{path}\t{secure}\t{exp}\t{name}\t{value}\n')
                count += 1
                continue
        
        # Tenta parsear como JSON (se começar com { ou [)
        if line.startswith('{') or line.startswith('['):
            import json
            try:
                data = json.loads(line)
                items = data if isinstance(data, list) else [data]
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
                        count += 1
            except:
                pass
            continue
        
        # Tenta parsear como name=value (formato simples)
        if '=' in line:
            parts = line.split('=', 1)
            name = parts[0].strip()
            value = parts[1].strip().rstrip(';')
            if name and value:
                f.write(f'.youtube.com\tTRUE\t/\tFALSE\t2147483647\t{name}\t{value}\n')
                count += 1

print(f'  ✓ Cookies reescritos em formato Netscape ({count} cookies)')
PYEOF
    return $?
}

# Priority 1: Render Secret File (mais recente, atualizado manualmente)
if [ -f /etc/secrets/cookies.txt ]; then
    echo "✓ Render Secret File encontrado em /etc/secrets/cookies.txt"
    cp /etc/secrets/cookies.txt /app/scraper/cookies.txt
    export YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt
    echo "✓ Cookies copiado do Secret File ($(wc -l < /app/scraper/cookies.txt) linhas)"
    convert_cookies
    COOKIE_SOURCE="Secret File"
fi

# Priority 2: YOUTUBE_COOKIES_BASE64 (fallback, se Secret File não existir)
if [ ! -f /app/scraper/cookies.txt ] && [ -n "$YOUTUBE_COOKIES_BASE64" ]; then
    echo "✓ YOUTUBE_COOKIES_BASE64 encontrada, decodificando..."
    echo "$YOUTUBE_COOKIES_BASE64" | base64 -d > /app/scraper/cookies.txt
    if [ -f /app/scraper/cookies.txt ] && [ -s /app/scraper/cookies.txt ]; then
        export YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt
        echo "✓ Cookies decodificados da base64 ($(wc -l < /app/scraper/cookies.txt) linhas)"
        convert_cookies
        COOKIE_SOURCE="BASE64"
    else
        echo "✗ Falha ao decodificar YOUTUBE_COOKIES_BASE64"
    fi
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
