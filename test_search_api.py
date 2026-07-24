"""
Teste de busca na API do Render.
"""
import requests

base_url = "https://suamusica-api.onrender.com"

# Testar a query que causou erro
query = "Marília"
print(f"Testando busca na API: '{query}'")
print("=" * 60)

try:
    response = requests.get(
        f"{base_url}/api/search",
        params={"q": query},
        timeout=30
    )
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"✓ Busca bem-sucedida!")
        print(f"  Resultados encontrados: {len(data)}")
        if isinstance(data, list):
            for i, result in enumerate(data[:3]):
                print(f"  {i+1}. {result.get('title', 'N/A')}")
    else:
        print(f"✗ Erro: {response.text}")
except Exception as e:
    print(f"✗ Exceção: {e}")
