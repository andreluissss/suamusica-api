"""
Teste de busca para reproduzir o erro.
"""
from scraper.scraper import YouTubeScraper

scraper = YouTubeScraper()

# Testar a query que causou erro
query = "Marília"
print(f"Testando busca: '{query}'")
print("=" * 60)

try:
    results = scraper.search(query, max_results=10)
    print(f"✓ Busca bem-sucedida!")
    print(f"  Resultados encontrados: {len(results)}")
    for i, result in enumerate(results[:3]):
        print(f"  {i+1}. {result.get('title', 'N/A')}")
except Exception as e:
    print(f"✗ Erro: {e}")
