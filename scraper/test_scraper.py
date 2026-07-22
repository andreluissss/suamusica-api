"""
Teste rápido do YouTube Scraper.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.scraper import YouTubeScraper

def test_search():
    """Testa a funcionalidade de busca."""
    print("=" * 60)
    print("TESTE: Busca por 'Nirvana'")
    print("=" * 60)
    
    scraper = YouTubeScraper()
    
    try:
        results = scraper.search("Nirvana", max_results=5)
        print(f"\n✓ Busca realizada! {len(results)} resultados encontrados.\n")
        
        for i, video in enumerate(results, 1):
            print(f"  {i}. {video['title']}")
            print(f"     Canal: {video['channel']}")
            print(f"     Duração: {video['duration']}")
            print(f"     Views: {video['views']:,}")
            print(f"     URL: {video['url']}")
            print()
        
        return results
        
    except Exception as e:
        print(f"\n✗ Erro no teste: {e}")
        import traceback
        traceback.print_exc()
        return []


def test_video_info(url):
    """Testa obtenção de informações de vídeo."""
    print("\n" + "=" * 60)
    print(f"TESTE: Informações do vídeo")
    print("=" * 60)
    
    scraper = YouTubeScraper()
    
    try:
        info = scraper.get_video_info(url)
        print(f"\n✓ Informações obtidas!\n")
        print(f"  Título: {info['title']}")
        print(f"  Canal: {info['channel']}")
        print(f"  Duração: {info['duration']}")
        print(f"  Views: {info['view_count']:,}")
        print(f"  Likes: {info['like_count']:,}")
        
        if info.get("audio_formats"):
            print(f"  Formatos de áudio disponíveis: {len(info['audio_formats'])}")
        
        return info
        
    except Exception as e:
        print(f"\n✗ Erro no teste: {e}")
        return None


if __name__ == "__main__":
    print("\n🚀 YOUTUBE MUSIC SCRAPER - TESTE\n")
    
    # Teste 1: Busca
    results = test_search()
    
    if results:
        # Teste 2: Informações do primeiro resultado
        test_video_info(results[0]["url"])
    
    print("\n" + "=" * 60)
    print("Teste concluído!")
    print("=" * 60)