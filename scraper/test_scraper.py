"""
Teste rápido do YouTube Scraper com cache e estratégias de fallback.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.scraper import YouTubeScraper, MemoryCache, compute_cache_key


def test_cache():
    """Testa o sistema de cache."""
    print("=" * 60)
    print("TESTE: MemoryCache")
    print("=" * 60)

    cache = MemoryCache(ttl_seconds=10)
    
    # Teste set/get
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1", "Cache get falhou"
    print("  ✓ set/get funciona")
    
    # Teste expiração
    import time
    cache_short = MemoryCache(ttl_seconds=1)
    cache_short.set("key2", "value2")
    time.sleep(1.5)
    assert cache_short.get("key2") is None, "Cache TTL falhou"
    print("  ✓ TTL funciona")
    
    # Teste remove
    cache.set("key3", "value3")
    cache.remove("key3")
    assert cache.get("key3") is None, "Cache remove falhou"
    print("  ✓ remove funciona")
    
    # Teste clear
    cache.set("key4", "value4")
    cache.clear()
    assert cache.get("key4") is None, "Cache clear falhou"
    print("  ✓ clear funciona")
    
    # Teste compute_cache_key
    key1 = compute_cache_key("test", param1="value1")
    key2 = compute_cache_key("test", param1="value1")
    assert key1 == key2, "Cache key deterministic falhou"
    print("  ✓ compute_cache_key é determinístico")
    
    print("\n✓ Cache testado com sucesso!\n")


def test_search():
    """Testa a funcionalidade de busca com cache."""
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
        
        # Teste de cache (segunda chamada deve ser instantânea)
        print("  Testando cache...")
        import time
        start = time.time()
        cached_results = scraper.search("Nirvana", max_results=5)
        cache_time = time.time() - start
        print(f"  Cache respondeu em {cache_time:.4f}s (deve ser < 0.1s)")
        assert len(cached_results) == len(results), "Cache retornou resultados diferentes"
        print("  ✓ Cache funcionou!")
        
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
        
        if info.get("categories"):
            print(f"  Categorias: {', '.join(info['categories'][:3])}")
        
        if info.get("tags"):
            print(f"  Tags: {len(info['tags'])}")
        
        if info.get("upload_date"):
            print(f"  Data de upload: {info['upload_date']}")
        
        return info
        
    except Exception as e:
        print(f"\n✗ Erro no teste: {e}")
        return None


def test_playlist_search():
    """Testa busca de playlists."""
    print("\n" + "=" * 60)
    print("TESTE: Busca de playlists")
    print("=" * 60)
    
    scraper = YouTubeScraper()
    
    try:
        playlists = scraper.search_playlists("melhores músicas rock", max_results=3)
        print(f"\n✓ {len(playlists)} playlists encontradas!\n")
        
        for i, pl in enumerate(playlists, 1):
            print(f"  {i}. {pl['title']}")
            print(f"     Canal: {pl['channel']}")
            print()
        
        return playlists
        
    except Exception as e:
        print(f"\n✗ Erro no teste: {e}")
        return []


def test_clear_cache():
    """Testa limpeza de cache."""
    print("\n" + "=" * 60)
    print("TESTE: Limpeza de cache")
    print("=" * 60)
    
    scraper = YouTubeScraper()
    
    try:
        scraper.clear_cache()
        print("✓ Cache limpo com sucesso!")
    except Exception as e:
        print(f"✗ Erro ao limpar cache: {e}")


def test_format_duration():
    """Testa formatação de duração."""
    print("\n" + "=" * 60)
    print("TESTE: Formatação de duração")
    print("=" * 60)
    
    assert YouTubeScraper._format_duration(0) == "00:00"
    assert YouTubeScraper._format_duration(30) == "0:30"
    assert YouTubeScraper._format_duration(65) == "1:05"
    assert YouTubeScraper._format_duration(3661) == "1:01:01"
    assert YouTubeScraper._format_duration(None) == "00:00"
    assert YouTubeScraper._format_duration("abc") == "00:00"
    
    print("✓ Todos os formatos de duração estão corretos!")


if __name__ == "__main__":
    print("\n" + "🚀 YOUTUBE MUSIC SCRAPER 2.0 - TESTES\n")
    
    # Teste 0: Cache
    test_cache()
    
    # Teste 1: Busca
    results = test_search()
    
    if results:
        # Teste 2: Informações do primeiro resultado
        test_video_info(results[0]["url"])
    
    # Teste 3: Playlists
    test_playlist_search()
    
    # Teste 4: Limpeza de cache
    test_clear_cache()
    
    # Teste 5: Formatação
    test_format_duration()
    
    print("\n" + "=" * 60)
    print("Teste concluído com sucesso!")
    print("=" * 60)