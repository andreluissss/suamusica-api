"""
Teste de stream no Render após correção de Content-Type.
"""
import requests

base_url = "https://suamusica-api.onrender.com"

# Testar stream
video_url = "https://www.youtube.com/watch?v=qPgwDlqdiD0"
print(f"Testando stream no Render: {video_url}")
print("=" * 60)

try:
    response = requests.get(
        f"{base_url}/api/stream",
        params={"url": video_url},
        timeout=30
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Stream obtido!")
        print(f"  Título: {data.get('title', 'N/A')}")
        stream_url = data.get('stream_url', '')
        print(f"  Stream URL: {stream_url[:100]}...")
        
        # Testar Content-Type do stream
        print("\nTestando Content-Type do stream...")
        head_response = requests.head(stream_url, timeout=10)
        print(f"  Content-Type: {head_response.headers.get('Content-Type')}")
        print(f"  Content-Length: {head_response.headers.get('Content-Length')}")
    else:
        print(f"✗ Erro: {response.text}")
except Exception as e:
    print(f"✗ Exceção: {e}")
