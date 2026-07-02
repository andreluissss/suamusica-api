import requests, time

BASE = "https://youtube-scraper-api-5iew.onrender.com"

# Wait for Render deploy
print("Aguardando deploy do Render...")
time.sleep(20)

# 1. Search for a video
print("=== Buscando vídeo ===")
r = requests.post(f"{BASE}/search", json={"query": "lofi music", "max_results": 1})
data = r.json()
video_id = data['results'][0]['video_id']
print(f"Video ID: {video_id}")
print(f"Título: {data['results'][0]['title']}")

# 2. Get stream URL
print("\n=== Obtendo URL de stream ===")
r = requests.post(f"{BASE}/stream-url", json={"video_id": video_id})
print(f"Status: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    print(f"Success: {data['success']}")
    print(f"Title: {data.get('title')}")
    print(f"Duration: {data.get('duration')}s")
    print(f"Format: {data.get('format')}")
    print(f"Extension: {data.get('ext')}")
    print(f"Stream URL: {str(data.get('stream_url', 'N/A'))[:100]}...")
else:
    print(f"Response: {r.text[:500]}")