"""
Servidor Flask para o YouTube Scraper.
API REST para busca, download e streaming com suporte a playlists.
"""

import os
import logging
from pathlib import Path

from flask import Flask, request, jsonify, send_file

from .scraper import YouTubeScraper

# Configure logging to show auth method info
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

app = Flask(__name__)
scraper = YouTubeScraper()


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": "YouTube Music Scraper API",
        "version": "2.0.0",
        "endpoints": {
            "GET /api/search?q=<query>&max=<n>": "Buscar músicas e playlists",
            "GET /api/playlist?url=<url>": "Ver faixas de uma playlist",
            "GET /api/info?url=<url>": "Info detalhada do vídeo",
            "GET /api/stream?url=<url>": "URL do stream de áudio",
            "GET /api/download?url=<url>": "Download MP3",
            "GET /api/download-playlist?url=<url>": "Baixar playlist toda",
            "GET /api/downloaded": "Listar baixados",
        },
    })


@app.route("/api/search", methods=["GET"])
def search():
    """
    Busca músicas/artistas/playlists.
    Query params: q (obrigatório), max (opcional, padrão 10)
    """
    query = request.args.get("q", "").strip()
    max_results = int(request.args.get("max", 10))

    if not query:
        return jsonify({"error": "Parâmetro 'q' é obrigatório"}), 400

    try:
        results = scraper.search(query, max_results=max_results)
        return jsonify({
            "query": query,
            "count": len(results),
            "results": results,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/playlist", methods=["GET"])
def playlist_tracks():
    """
    Obtém as faixas individuais de uma playlist.
    Query params: url (obrigatório)
    """
    url = request.args.get("url", "").strip()

    if not url:
        return jsonify({"error": "Parâmetro 'url' é obrigatório"}), 400

    try:
        tracks = scraper.get_playlist_tracks(url)
        return jsonify({
            "url": url,
            "count": len(tracks),
            "tracks": tracks,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/info", methods=["GET"])
def video_info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Parâmetro 'url' é obrigatório"}), 400

    try:
        info = scraper.get_video_info(url)
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stream", methods=["GET"])
def stream():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Parâmetro 'url' é obrigatório"}), 400

    try:
        audio_url, title = scraper.get_audio_stream_url(url)
        return jsonify({"title": title, "stream_url": audio_url, "source_url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download", methods=["GET"])
def download():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Parâmetro 'url' é obrigatório"}), 400

    try:
        filepath = scraper.download_audio(url)
        filename = Path(filepath).name
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype="audio/mpeg",
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download-playlist", methods=["GET"])
def download_playlist():
    """
    Baixa todas as músicas de uma playlist como MP3s separados.
    Retorna lista de arquivos baixados.
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Parâmetro 'url' é obrigatório"}), 400

    try:
        files = scraper.download_playlist_audios(url)
        return jsonify({
            "url": url,
            "downloaded": len(files),
            "files": files,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/downloaded", methods=["GET"])
def list_downloaded():
    try:
        files = scraper.list_downloaded()
        return jsonify({"count": len(files), "files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    """Limpa os caches internos do scraper."""
    try:
        scraper.clear_cache()
        return jsonify({"status": "ok", "message": "Cache limpo com sucesso"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    """Endpoint de saúde do serviço."""
    return jsonify({
        "status": "ok",
        "version": "2.1.0",
        "download_dir": scraper.download_dir,
        "auth_method": (
            "cookies" if ("cookiesfrombrowser" in scraper._common_opts or "cookiefile" in scraper._common_opts)
            else "anonymous"
        ),
    })


def run_server(host="0.0.0.0", port=5000, debug=False):
    print(f"\n🎵 YouTube Music Scraper API v2.1")
    print(f"   Rodando em: http://{host}:{port}")
    print(f"   Downloads: {scraper.download_dir}")
    print(f"\n📌 Exemplos:")
    print(f"   Busca:     http://{host}:{port}/api/search?q=Nirvana")
    print(f"   Playlist:  http://{host}:{port}/api/playlist?url=PLAYLIST_URL")
    print(f"   Stream:    http://{host}:{port}/api/stream?url=YOUTUBE_URL")
    print(f"   Download:  http://{host}:{port}/api/download?url=YOUTUBE_URL")
    print(f"   Health:    http://{host}:{port}/api/health")
    app.run(host=host, port=port, debug=debug)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="YouTube Music Scraper API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--download-dir")
    args = parser.parse_args()

    global scraper
    if args.download_dir:
        scraper = YouTubeScraper(download_dir=args.download_dir)

    run_server(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()