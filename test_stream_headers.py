"""
Teste de stream URL com diferentes headers para verificar por que não toca no app.
"""
import requests
from scraper.scraper import YouTubeScraper

scraper = YouTubeScraper()

# Testar stream URL
video_url = "https://www.youtube.com/watch?v=qPgwDlqdiD0"
print(f"Testando stream URL: {video_url}")
print("=" * 60)

try:
    stream_url, title = scraper.get_audio_stream_url(video_url)
    print(f"✓ Stream URL obtida: {stream_url[:100]}...")
    print(f"  Título: {title}")
    print()

    # Teste 1: Sem headers (como o app pode estar fazendo)
    print("Teste 1: Sem headers")
    try:
        response = requests.get(stream_url, stream=True, timeout=10)
        print(f"  Status: {response.status_code}")
        print(f"  Headers: {dict(response.headers)}")
        print(f"  Content-Type: {response.headers.get('Content-Type')}")
        print(f"  Content-Length: {response.headers.get('Content-Length')}")
    except Exception as e:
        print(f"  ✗ Erro: {e}")
    print()

    # Teste 2: Com User-Agent
    print("Teste 2: Com User-Agent")
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = requests.get(stream_url, headers=headers, stream=True, timeout=10)
        print(f"  Status: {response.status_code}")
        print(f"  Content-Type: {response.headers.get('Content-Type')}")
    except Exception as e:
        print(f"  ✗ Erro: {e}")
    print()

    # Teste 3: Com headers completos (como o scraper usa)
    print("Teste 3: Com headers completos (User-Agent + Accept)")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
        }
        response = requests.get(stream_url, headers=headers, stream=True, timeout=10)
        print(f"  Status: {response.status_code}")
        print(f"  Content-Type: {response.headers.get('Content-Type')}")
        print(f"  Content-Length: {response.headers.get('Content-Length')}")
    except Exception as e:
        print(f"  ✗ Erro: {e}")

except Exception as e:
    print(f"✗ Erro ao obter stream: {e}")
