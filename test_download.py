import requests

BASE = "https://youtube-scraper-api-5iew.onrender.com"

# 1. Search for a video
print("=== Buscando vídeo ===")
r = requests.post(f"{BASE}/search", json={"query": "lofi music", "max_results": 1})
data = r.json()
video_id = data['results'][0]['video_id']
print(f"Video ID: {video_id}")
print(f"Título: {data['results'][0]['title']}")

# 2. Try to download
print("\n=== Solicitando download ===")
r = requests.post(f"{BASE}/download", json={"video_id": video_id, "format": "mp3"})
print(f"Status: {r.status_code}")
print(f"Resposta: {r.json()}")