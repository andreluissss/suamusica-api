"""
Teste da API no Render com proxy e cookies configurados.
"""
import requests
import json
import time

base_url = "https://suamusica-api.onrender.com"

# Vídeo de teste (Nirvana - Smells Like Teen Spirit)
test_video = "https://www.youtube.com/watch?v=hTWKbfoikeg"

print("=" * 60)
print("TESTANDO API NO RENDER")
print("=" * 60)
print(f"URL base: {base_url}")
print(f"Vídeo teste: {test_video}")
print()

# Teste 1: Stream
print("-" * 60)
print("TESTE 1: Obter stream URL")
print("-" * 60)
try:
    response = requests.get(
        f"{base_url}/api/stream",
        params={"url": test_video},
        timeout=30
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Stream obtido com sucesso!")
        print(f"  Título: {data.get('title', 'N/A')}")
        print(f"  Stream URL: {data.get('stream_url', 'N/A')[:80]}...")
    else:
        print(f"✗ Erro: {response.text}")
except Exception as e:
    print(f"✗ Exceção: {e}")

print()

# Teste 2: Info
print("-" * 60)
print("TESTE 2: Obter informações do vídeo")
print("-" * 60)
try:
    response = requests.get(
        f"{base_url}/api/info",
        params={"url": test_video},
        timeout=30
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Info obtida com sucesso!")
        print(f"  Título: {data.get('title', 'N/A')}")
        print(f"  Canal: {data.get('channel', 'N/A')}")
        print(f"  Duração: {data.get('duration', 'N/A')}")
    else:
        print(f"✗ Erro: {response.text}")
except Exception as e:
    print(f"✗ Exceção: {e}")

print()

# Teste 3: Download (apenas verifica se inicia)
print("-" * 60)
print("TESTE 3: Download (verificação inicial)")
print("-" * 60)
try:
    response = requests.get(
        f"{base_url}/api/download",
        params={"url": test_video},
        timeout=30
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print(f"✓ Download iniciado com sucesso!")
        print(f"  Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        print(f"  Content-Disposition: {response.headers.get('Content-Disposition', 'N/A')}")
    else:
        print(f"✗ Erro: {response.text}")
except Exception as e:
    print(f"✗ Exceção: {e}")

print()
print("=" * 60)
print("TESTES CONCLUÍDOS")
print("=" * 60)
