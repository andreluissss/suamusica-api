"""
Teste de download em formato original (webm/opus).
"""
from scraper.scraper import YouTubeScraper
import os

scraper = YouTubeScraper()

# Testar download em formato original
video_url = "https://www.youtube.com/watch?v=hTWKbfoikeg"
print(f"Testando download em formato original: {video_url}")
print("=" * 60)

try:
    filepath = scraper.download_audio(video_url, format="original")
    print(f"✓ Download bem-sucedido!")
    print(f"  Caminho: {filepath}")
    print(f"  Tamanho: {os.path.getsize(filepath) / 1024 / 1024:.2f} MB")
    print(f"  Extensão: {os.path.splitext(filepath)[1]}")
except Exception as e:
    print(f"✗ Erro: {e}")

print("\n" + "=" * 60)
print("Testando download em formato MP3 (padrão)")
print("=" * 60)

try:
    filepath_mp3 = scraper.download_audio(video_url, format="mp3")
    print(f"✓ Download bem-sucedido!")
    print(f"  Caminho: {filepath_mp3}")
    print(f"  Tamanho: {os.path.getsize(filepath_mp3) / 1024 / 1024:.2f} MB")
    print(f"  Extensão: {os.path.splitext(filepath_mp3)[1]}")
except Exception as e:
    print(f"✗ Erro: {e}")
