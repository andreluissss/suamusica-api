"""
SuaMusica Scraper API
---------------------
API REST que faz scraping do SuaMusica.com.br em tempo real.
Pronto para deploy no Railway.

Endpoints:
  GET /search?q={termo}       - Busca artistas, albuns, playlists
  GET /artist/{username}       - Dados do artista + albuns
  GET /album/{username}/{slug} - Tracks do album com links MP3

Uso local: uvicorn suamusica_api:app --reload --port 8000
"""

import os
import re
import json
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ─── Config ───────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("suamusica-api")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/json,*/*",
})

BASE_URL = "https://suamusica.com.br"

app = FastAPI(
    title="SuaMusica Scraper API",
    description="API que busca dados do SuaMusica.com.br em tempo real.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Helpers ───────────────────────────────────────────────────────────

def _fetch_next_data(url: str) -> Optional[dict]:
    """Faz GET e retorna o JSON do __NEXT_DATA__."""
    try:
        resp = SESSION.get(url, timeout=15)  # Reduzido de 30 para 15 segundos
        if resp.status_code == 404:
            logger.warning(f"404 Not Found: {url}")
            return None
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script:
            return json.loads(script.get_text())
        logger.warning(f"__NEXT_DATA__ not found in {url}")
        return None
    except requests.exceptions.Timeout:
        logger.error(f"Timeout ao acessar {url} (15s)")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro de requisição ao acessar {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None


def _page_props(url: str) -> Optional[dict]:
    """Retorna props.pageProps do __NEXT_DATA__ de uma URL."""
    data = _fetch_next_data(url)
    if data:
        return data.get("props", {}).get("pageProps")
    return None


def _build_artist_dict(user: dict, albums: list) -> dict:
    """Converte dados do artista para JSON padrao."""
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "username": user.get("username"),
        "avatar": user.get("avatar"),
        "cover": user.get("cover"),
        "plays": user.get("plays"),
        "downloads": user.get("download"),
        "uploads": user.get("uploads"),
        "city": user.get("city"),
        "state": user.get("state"),
        "followers": user.get("followers"),
        "following": user.get("follow"),
        "is_vip": user.get("isVip"),
        "is_verified": user.get("isVerified"),
        "albums": [
            {
                "id": a.get("id"),
                "title": a.get("title"),
                "slug": a.get("slug"),
                "cover": a.get("cover"),
                "plays": a.get("plays"),
                "downloads": a.get("downloads"),
                "tracks": a.get("total"),
                "date": a.get("sendDate"),
            }
            for a in (albums or [])
        ],
    }


def _build_album_dict(album: dict) -> dict:
    """Converte dados do album para JSON padrao."""
    return {
        "id": album.get("id"),
        "name": album.get("name"),
        "artist": album.get("userName"),
        "artist_id": album.get("ownerId"),
        "slug": album.get("slug"),
        "category": album.get("catName"),
        "category_id": album.get("catId"),
        "cover": album.get("bigCover"),
        "cover_small": album.get("cover"),
        "plays": album.get("plays"),
        "downloads": album.get("downloads"),
        "size": album.get("size"),
        "likes": album.get("likes"),
        "is_vip": album.get("isVip"),
        "released": bool(album.get("released")),
        "date": album.get("sendDate"),
        "tracks": [
            {
                "id": f.get("id"),
                "title": f.get("file"),
                "position": f.get("position", 0) + 1,
                "mp3_url": f.get("path"),
                "stream_url": f.get("stream"),
                "is_downloadable": bool(f.get("isDownloadable")),
                "is_explicit": bool(f.get("isExplicit")),
            }
            for f in (album.get("files") or [])
        ],
    }


# ─── Endpoints ─────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "api": "SuaMusica Scraper",
        "version": "1.0.0",
        "endpoints": {
            "search": "/search?q={termo}",
            "artist": "/artist/{username}",
            "album": "/album/{username}/{slug}",
        },
    }


@app.get("/search")
def search(q: str = Query(..., description="Termo de busca")):
    """
    Busca artistas, albuns, noticias e videos no SuaMusica.
    """
    url = f"{BASE_URL}/busca?q={q}"
    pp = _page_props(url)
    if not pp:
        raise HTTPException(500, "Nao foi possivel buscar os dados.")

    return {
        "query": q,
        "profiles": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "username": p.get("username"),
                "avatar": p.get("avatar"),
                "is_vip": p.get("isVip"),
                "is_verified": p.get("isVerified"),
            }
            for p in (pp.get("profiles") or [])
        ],
        "albums": [
            {
                "id": a.get("id"),
                "title": a.get("title"),
                "artist": a.get("name"),
                "artist_username": a.get("username"),
                "cover": a.get("cover"),
                "plays": a.get("plays"),
                "downloads": a.get("downloads"),
                "is_verified": a.get("isVerified"),
            }
            for a in (pp.get("recommendedAlbums") or [])
        ],
        "news": pp.get("news") or [],
        "videos": (pp.get("videos") or {}).get("items") or [],
    }


@app.get("/artist/{username:path}")
def artist(username: str):
    """
    Retorna dados do artista + todos os albuns.
    """
    username = username.strip("/")
    url = f"{BASE_URL}/{username}"
    pp = _page_props(url)

    if not pp:
        raise HTTPException(404, f"Artista '{username}' nao encontrado ou timeout.")

    user = pp.get("user")
    if not user:
        raise HTTPException(404, f"Artista '{username}' nao encontrado.")

    albums = pp.get("userAlbums") or []
    result = _build_artist_dict(user, albums)

    return result


@app.get("/album/{username:path}")
def album(username: str, slug: Optional[str] = Query(None)):
    """
    Retorna dados do album com tracks (MP3).
    
    Uso: /album/natanzinhoofc/natanzinho-lima-na-liga-em-sampa
    Ou:  /album/natanzinhoofc?slug=natanzinho-lima-na-liga-em-sampa
    """
    parts = username.strip("/").split("/")
    if len(parts) == 2:
        user = parts[0]
        slug_val = parts[1]
    elif len(parts) == 1 and slug:
        user = parts[0]
        slug_val = slug
    else:
        raise HTTPException(
            400,
            "Use /album/{username}/{slug} ou /album/{username}?slug={slug}",
        )

    url = f"{BASE_URL}/{user}/{slug_val}"
    pp = _page_props(url)

    if not pp:
        raise HTTPException(
            404, f"Album '{slug_val}' do artista '{user}' nao encontrado ou timeout."
        )

    album_data = pp.get("album")
    if not album_data:
        raise HTTPException(
            404, f"Album '{slug_val}' do artista '{user}' nao encontrado."
        )

    return _build_album_dict(album_data)


# ─── Health ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ─── Main (para execucao local) ────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("suamusica_api:app", host="0.0.0.0", port=port, reload=True)