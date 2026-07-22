"""
Teste de download e streaming do YouTube Scraper.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.scraper import YouTubeScraper

scraper = YouTubeScraper(download_dir="downloads_test")

# Teste 1: Obter stream URL
print("=" * 60)
print("TESTE: Obter stream URL")
print("=" * 60)
try:
    stream_url, title = scraper.get_audio_stream_url(
        "https://www.youtube.com/watch?v=hTWKbfoikeg"
    )
    print(f"  ✓ Stream obtido com sucesso!")
    print(f"  Título: {title}")
    print(f"  URL: {stream_url[:80]}...")
except Exception as e:
    print(f"  ✗ Erro: {e}")

# Teste 2: Download de áudio
print("\n" + "=" * 60)
print("TESTE: Download MP3")
print("=" * 60)
try:
    filepath = scraper.download_audio(
        "https://www.youtube.com/watch?v=hTWKbfoikeg",
        filename="Nirvana_Teste"
    )
    print(f"  ✓ Download concluído!")
    print(f"  Arquivo: {filepath}")
    
    if os.path.exists(filepath):
        size = os.path.getsize(filepath)
        print(f"  Tamanho: {size / 1024 / 1024:.2f} MB")
except Exception as e:
    print(f"  ✗ Erro: {e}")

print("\n" + "=" * 60)
print("Teste concluído!")
print("=" * 60)