"""
Teste de download com vídeo alternativo.
"""
from scraper.scraper import YouTubeScraper

scraper = YouTubeScraper(download_dir="downloads_test")

# Vídeos alternativos para teste
test_videos = [
    "https://www.youtube.com/watch?v=hTWKbfoikeg",  # Nirvana
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",  # Me at the zoo (primeiro vídeo do YouTube)
    "https://www.youtube.com/watch?v=9bZkp7q19f0",  # PSY - Gangnam Style
]

for video in test_videos:
    print(f"\n{'='*60}")
    print(f"Testando: {video}")
    print('='*60)
    
    try:
        # Testa stream primeiro
        stream_url, title = scraper.get_audio_stream_url(video)
        print(f"✓ Stream: {title[:50]}...")
        
        # Testa download
        file_path = scraper.download_audio(video)
        print(f"✓ Download: {file_path}")
        
    except Exception as e:
        print(f"✗ Erro: {str(e)[:200]}")
