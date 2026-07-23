"""
Teste simples de proxy HTTP.
"""
import requests
import sys

proxy_url = "http://64.112.184.210:3128"

print(f"Testando proxy: {proxy_url}")
print("-" * 50)

try:
    # Teste 1: Conexão simples
    response = requests.get(
        "http://httpbin.org/ip",
        proxies={"http": proxy_url, "https": proxy_url},
        timeout=10
    )
    print(f"✓ Proxy funcionando!")
    print(f"  IP através do proxy: {response.json()}")
except requests.exceptions.ProxyError as e:
    print(f"✗ Erro de proxy: {e}")
    sys.exit(1)
except requests.exceptions.Timeout:
    print(f"✗ Timeout - proxy não respondeu")
    sys.exit(1)
except Exception as e:
    print(f"✗ Erro: {e}")
    sys.exit(1)

# Teste 2: Acesso ao YouTube
try:
    response = requests.get(
        "https://www.youtube.com",
        proxies={"http": proxy_url, "https": proxy_url},
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    if response.status_code == 200:
        print(f"✓ YouTube acessível através do proxy")
    else:
        print(f"⚠ YouTube retornou status {response.status_code}")
except Exception as e:
    print(f"✗ Erro ao acessar YouTube: {e}")

print("-" * 50)
print("Se o proxy funcionou, configure no Render:")
print(f"YOUTUBE_PROXY = {proxy_url}")
