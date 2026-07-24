"""
YouTube Hybrid Scraper v3.0
========================================
Motor de extração híbrido com 3 camadas de fallback, suporte a múltiplos formatos,
rotação de proxies/headers, processamento assíncrono e pós-processamento inteligente.

Arquitetura:
  Layer 1 (yt-dlp): Extração direta via yt-dlp com cache de 5 minutos.
  Layer 2 (Mobile): Parsing manual da página mobile (m.youtube.com) com regex + BS4.
  Layer 3 (Emergency): Fallback para API externa ou parsing DASH.

Inspirado em Snaptube, Muka e yt-dlp para máxima velocidade e confiabilidade.
"""

import os
import re
import json
import time
import random
import logging
import base64
import tempfile
import hashlib
import subprocess
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────

# Itags de áudio conhecidas com metadados
AUDIO_ITAGS: Dict[str, Dict[str, Any]] = {
    "250": {"ext": "webm", "abr": 70, "codec": "opus", "channels": 1},
    "249": {"ext": "webm", "abr": 50, "codec": "opus", "channels": 1},
    "140": {"ext": "m4a",  "abr": 128, "codec": "aac",  "channels": 2},
    "251": {"ext": "webm", "abr": 160, "codec": "opus", "channels": 2},
    "256": {"ext": "m4a",  "abr": 192, "codec": "aac",  "channels": 2},
    "258": {"ext": "m4a",  "abr": 384, "codec": "aac",  "channels": 2},
    "325": {"ext": "webm", "abr": 96,  "codec": "opus", "channels": 2},
    "328": {"ext": "webm", "abr": 96,  "codec": "opus", "channels": 2},
    "599": {"ext": "webm", "abr": 30,  "codec": "opus", "channels": 1},
    "600": {"ext": "webm", "abr": 50,  "codec": "opus", "channels": 1},
    "774": {"ext": "webm", "abr": 96,  "codec": "opus", "channels": 2},
}

# Itags de vídeo conhecidas com metadados
VIDEO_ITAGS: Dict[str, Dict[str, Any]] = {
    "394": {"ext": "mp4",  "height": 144,  "fps": 30, "codec": "avc1"},
    "395": {"ext": "mp4",  "height": 240,  "fps": 30, "codec": "avc1"},
    "396": {"ext": "mp4",  "height": 360,  "fps": 30, "codec": "avc1"},
    "397": {"ext": "mp4",  "height": 480,  "fps": 30, "codec": "avc1"},
    "398": {"ext": "mp4",  "height": 720,  "fps": 30, "codec": "avc1"},
    "399": {"ext": "mp4",  "height": 1080, "fps": 30, "codec": "avc1"},
    "400": {"ext": "mp4",  "height": 1440, "fps": 30, "codec": "avc1"},
    "401": {"ext": "mp4",  "height": 2160, "fps": 30, "codec": "avc1"},
    "402": {"ext": "mp4",  "height": 4320, "fps": 30, "codec": "avc1"},
    "298": {"ext": "mp4",  "height": 720,  "fps": 60, "codec": "avc1"},
    "299": {"ext": "mp4",  "height": 1080, "fps": 60, "codec": "avc1"},
    "334": {"ext": "webm", "height": 144,  "fps": 30, "codec": "vp9"},
    "335": {"ext": "webm", "height": 240,  "fps": 30, "codec": "vp9"},
    "336": {"ext": "webm", "height": 360,  "fps": 30, "codec": "vp9"},
    "337": {"ext": "webm", "height": 480,  "fps": 30, "codec": "vp9"},
    "338": {"ext": "webm", "height": 720,  "fps": 30, "codec": "vp9"},
    "339": {"ext": "webm", "height": 1080, "fps": 30, "codec": "vp9"},
    "340": {"ext": "webm", "height": 1440, "fps": 30, "codec": "vp9"},
    "341": {"ext": "webm", "height": 2160, "fps": 30, "codec": "vp9"},
    "342": {"ext": "webm", "height": 4320, "fps": 30, "codec": "vp9"},
    "302": {"ext": "webm", "height": 720,  "fps": 60, "codec": "vp9"},
    "303": {"ext": "webm", "height": 1080, "fps": 60, "codec": "vp9"},
    "308": {"ext": "webm", "height": 1440, "fps": 60, "codec": "vp9"},
    "315": {"ext": "webm", "height": 2160, "fps": 60, "codec": "vp9"},
    "272": {"ext": "webm", "height": 4320, "fps": 60, "codec": "vp9"},
}

# Mapeamento de resolução para altura
RESOLUTION_MAP: Dict[str, int] = {
    "144p": 144, "240p": 240, "360p": 360, "480p": 480,
    "720p": 720, "720p60": 720, "1080p": 1080, "1080p60": 1080,
    "1440p": 1440, "1440p60": 1440, "2160p": 2160, "2160p60": 2160,
    "4K": 2160, "8K": 4320,
}

# User-Agents atualizados para rotação
USER_AGENTS: List[str] = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Firefox macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:127.0) Gecko/20100101 Firefox/127.0",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    # Mobile Chrome Android
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.122 Mobile Safari/537.36",
    # Mobile Safari iOS
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    # Safari macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

# ──────────────────────────────────────────────────────────────────────
# Data Classes
# ──────────────────────────────────────────────────────────────────────

@dataclass
class FormatInfo:
    """Informações de um formato de stream."""
    itag: str
    ext: str
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[int] = None
    bitrate: Optional[int] = None
    abr: Optional[float] = None
    codec: Optional[str] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    filesize: Optional[int] = None
    url: Optional[str] = None
    is_audio: bool = False
    is_video: bool = False
    has_audio: bool = False
    has_video: bool = False
    quality_label: Optional[str] = None

    @property
    def resolution(self) -> str:
        if self.height:
            if self.height >= 4320:
                return "8K"
            elif self.height >= 2160:
                return "4K"
            elif self.height >= 1440:
                return "1440p"
            elif self.height >= 1080:
                return "1080p"
            elif self.height >= 720:
                return "720p"
            elif self.height >= 480:
                return "480p"
            elif self.height >= 360:
                return "360p"
            elif self.height >= 240:
                return "240p"
            elif self.height >= 144:
                return "144p"
        return "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VideoMetadata:
    """Metadados completos de um vídeo."""
    id: str
    title: str
    channel: str
    channel_id: Optional[str] = None
    duration: int = 0
    duration_str: str = "00:00"
    thumbnail: Optional[str] = None
    thumbnails: List[Dict] = field(default_factory=list)
    description: str = ""
    view_count: int = 0
    like_count: int = 0
    upload_date: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    is_live: bool = False
    is_age_restricted: bool = False
    is_private: bool = False
    formats: List[FormatInfo] = field(default_factory=list)
    audio_formats: List[FormatInfo] = field(default_factory=list)
    video_formats: List[FormatInfo] = field(default_factory=list)
    best_audio: Optional[FormatInfo] = None
    best_video: Optional[FormatInfo] = None
    captions: Dict[str, Any] = field(default_factory=dict)
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "channel": self.channel,
            "channel_id": self.channel_id,
            "duration": self.duration,
            "duration_str": self.duration_str,
            "thumbnail": self.thumbnail,
            "thumbnails": self.thumbnails,
            "description": self.description[:500] if self.description else "",
            "view_count": self.view_count,
            "like_count": self.like_count,
            "upload_date": self.upload_date,
            "categories": self.categories,
            "tags": self.tags[:20],
            "is_live": self.is_live,
            "is_age_restricted": self.is_age_restricted,
            "is_private": self.is_private,
            "formats": [f.to_dict() for f in self.formats],
            "audio_formats": [f.to_dict() for f in self.audio_formats],
            "video_formats": [f.to_dict() for f in self.video_formats],
            "best_audio": self.best_audio.to_dict() if self.best_audio else None,
            "best_video": self.best_video.to_dict() if self.best_video else None,
            "captions": list(self.captions.keys()) if self.captions else [],
            "url": self.url,
        }


@dataclass
class ExtractionLog:
    """Log de uma extração."""
    url: str
    layer: str  # 'yt-dlp', 'mobile', 'emergency'
    success: bool
    response_time: float
    formats_found: int
    file_size: Optional[int] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
# Cache
# ──────────────────────────────────────────────────────────────────────

class MemoryCache:
    """Cache em memória com TTL configurável."""

    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, Tuple[Any, datetime]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            data, expiry = self._cache[key]
            if datetime.now() < expiry:
                return data
            del self._cache[key]
        return None

    def set(self, key: str, value: Any):
        self._cache[key] = (value, datetime.now() + timedelta(seconds=self._ttl))

    def clear(self):
        self._cache.clear()

    def remove(self, key: str):
        self._cache.pop(key, None)


def compute_cache_key(*args, **kwargs) -> str:
    """Gera chave de cache única."""
    raw = str(args) + str(sorted(kwargs.items()))
    return hashlib.md5(raw.encode()).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# Proxy Pool
# ──────────────────────────────────────────────────────────────────────

class ProxyPool:
    """
    Pool de proxies com rotação automática.
    Suporta SOCKS5 e HTTP/HTTPS.
    """

    def __init__(self):
        self._proxies: List[str] = []
        self._blacklist: Set[str] = set()
        self._current_index = 0
        self._load_from_env()

    def _load_from_env(self):
        """Carrega proxies da variável de ambiente."""
        proxy_list = os.environ.get("YOUTUBE_PROXY_LIST", "")
        if proxy_list:
            self._proxies = [p.strip() for p in proxy_list.split(",") if p.strip()]

        # Proxy único também é aceito
        single_proxy = os.environ.get("YOUTUBE_PROXY", "")
        if single_proxy and single_proxy not in self._proxies:
            self._proxies.append(single_proxy)

    def add_proxy(self, proxy: str):
        if proxy and proxy not in self._proxies:
            self._proxies.append(proxy)

    def get_proxy(self) -> Optional[str]:
        """Retorna o próximo proxy disponível (round-robin)."""
        available = [p for p in self._proxies if p not in self._blacklist]
        if not available:
            return None
        proxy = available[self._current_index % len(available)]
        self._current_index += 1
        return proxy

    def blacklist(self, proxy: str):
        """Marca um proxy como falho."""
        if proxy:
            self._blacklist.add(proxy)
            logger.warning(f"Proxy blacklisted: {proxy}")

    def reset(self):
        """Limpa a blacklist."""
        self._blacklist.clear()

    @property
    def has_proxies(self) -> bool:
        return len(self._proxies) > 0

    @property
    def available_count(self) -> int:
        return len([p for p in self._proxies if p not in self._blacklist])


# ──────────────────────────────────────────────────────────────────────
# YouTube Hybrid Scraper
# ──────────────────────────────────────────────────────────────────────

class YouTubeScraper:
    """
    Motor de scraping híbrido com 3 camadas de fallback.

    Camadas:
      1. yt-dlp (rápido, cache de 5 min)
      2. Mobile page parsing (m.youtube.com) com regex + BS4
      3. Emergency: API externa / DASH parsing
    """

    # Limites de tempo
    LAYER1_TIMEOUT = 15  # segundos para yt-dlp
    LAYER2_TIMEOUT = 10  # segundos para mobile page
    LAYER3_TIMEOUT = 20  # segundos para emergency

    def __init__(self, download_dir: Optional[str] = None):
        self.download_dir = download_dir or os.path.join(
            os.path.expanduser("~"), "YouTubeDownloads"
        )
        os.makedirs(self.download_dir, exist_ok=True)

        # Caches
        self._info_cache = MemoryCache(ttl_seconds=300)   # 5 min
        self._search_cache = MemoryCache(ttl_seconds=120)  # 2 min
        self._stream_cache = MemoryCache(ttl_seconds=300)  # 5 min

        # Proxy pool
        self._proxy_pool = ProxyPool()

        # Logs de extração
        self._extraction_logs: List[ExtractionLog] = []

        # Rate limiting
        self._last_request_time = 0.0
        self._min_delay = 0.5
        self._max_delay = 2.0

        # Cookies / Auth
        self._temp_cookie_file = None
        self._setup_auth()

        # Headers
        self._current_headers = self._generate_headers()

        # Configuração base yt-dlp
        self._common_opts = self._build_common_opts()

        # Estratégias de cliente yt-dlp
        self._client_strategies = self._build_client_strategies()

        # Detecção de ambiente cloud
        self._is_cloud = self._detect_cloud()

        logger.info(f"YouTubeScraper v3.0 inicializado")
        logger.info(f"  Download dir: {self.download_dir}")
        logger.info(f"  Cloud env: {self._is_cloud}")
        logger.info(f"  Proxies: {self._proxy_pool.available_count} disponíveis")

    # ──────────────────────────────────────────────────────────────
    # Setup
    # ──────────────────────────────────────────────────────────────

    def _setup_auth(self):
        """Configura autenticação via cookies."""
        cookies_browser = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "")
        cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE", "")
        cookies_base64 = os.environ.get("YOUTUBE_COOKIES_BASE64", "")

        self._auth_method = "anonymous"
        self._cookies_opts: Dict[str, Any] = {}

        if cookies_browser:
            browser = cookies_browser.strip().lower()
            self._cookies_opts["cookiesfrombrowser"] = browser
            self._auth_method = f"browser:{browser}"
            logger.info(f"Auth: cookies do navegador '{browser}'")
        elif cookies_file and os.path.exists(cookies_file):
            self._cookies_opts["cookiefile"] = cookies_file
            self._auth_method = f"file:{cookies_file}"
            logger.info(f"Auth: arquivo de cookies '{cookies_file}'")
        elif cookies_base64:
            try:
                content = base64.b64decode(cookies_base64).decode("utf-8")
                tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
                tmp.write(content)
                tmp.close()
                self._temp_cookie_file = tmp.name
                self._cookies_opts["cookiefile"] = tmp.name
                self._auth_method = "base64"
                logger.info("Auth: cookies base64 (env var)")
            except Exception as e:
                logger.warning(f"Falha ao decodificar cookies base64: {e}")

        if self._auth_method == "anonymous":
            logger.info("Auth: anônimo (sem cookies)")

    def _build_common_opts(self) -> Dict[str, Any]:
        """Constrói opções base para yt-dlp."""
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "http_headers": dict(self._current_headers),
            "extractor_args": {
                "youtube": {
                    "include_dash_manifest": True,
                    "include_info_json": True,
                    "player_client": ["android", "ios"],
                }
            },
            "extractor_retries": 2,
            "file_access_retries": 2,
            "fragment_retries": 2,
            "retries": 2,
            "skip_unavailable_fragments": True,
            "socket_timeout": self.LAYER1_TIMEOUT,
            "js_runtimes": {"node": {}},
        }
        # Aplica cookies
        opts.update(self._cookies_opts)
        # Aplica proxy se disponível
        proxy = self._proxy_pool.get_proxy()
        if proxy:
            opts["proxy"] = proxy
        return opts

    def _build_client_strategies(self) -> List[Dict[str, Any]]:
        """Constrói estratégias de cliente para fallback no yt-dlp."""
        return [
            {"extractor_args": {"youtube": {"player_client": ["android", "ios"]}}},
            {"extractor_args": {"youtube": {"player_client": ["web_safari"]}}},
            {"extractor_args": {"youtube": {"player_client": ["android_tv"]}}},
            {"extractor_args": {"youtube": {"player_client": ["web_creator"]}}},
            {"extractor_args": {"youtube": {"player_client": ["mweb", "web"]}}},
            {"extractor_args": {"youtube": {"player_client": ["ios", "tvos"]}}},
            {"extractor_args": {"youtube": {"player_client": ["tv_embedded"]}}},
        ]

    def _generate_headers(self) -> Dict[str, str]:
        """Gera headers HTTP realistas com User-Agent aleatório."""
        ua = random.choice(USER_AGENTS)
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
            "Connection": "keep-alive",
        }

    def _rotate_headers(self):
        """Rotaciona headers (User-Agent)."""
        self._current_headers = self._generate_headers()
        self._common_opts["http_headers"] = dict(self._current_headers)

    def _detect_cloud(self) -> bool:
        """Detecta ambiente cloud."""
        indicators = [
            os.environ.get("RENDER", ""),
            os.environ.get("DYNO", ""),
            os.environ.get("RAILWAY_ENVIRONMENT", ""),
            os.environ.get("FLY_APP_NAME", ""),
            os.environ.get("K_SERVICE", ""),
            os.environ.get("AWS_EXECUTION_ENV", ""),
        ]
        return any(indicators) or os.path.exists("/.dockerenv")

    def _apply_rate_limit(self):
        """Rate limiting com jitter."""
        elapsed = time.time() - self._last_request_time
        delay = random.uniform(self._min_delay, self._max_delay)
        if elapsed < delay:
            sleep_time = delay - elapsed
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    # ──────────────────────────────────────────────────────────────
    # Layer 1: yt-dlp
    # ──────────────────────────────────────────────────────────────

    def _extract_layer1(self, url: str, download: bool = False,
                        opts_override: Optional[Dict] = None) -> Optional[Dict]:
        """
        Camada 1: Extração via yt-dlp.
        Tenta múltiplas estratégias de cliente em cascata.
        """
        start = time.time()
        last_error = None

        # Tenta com cookies primeiro (se disponíveis)
        if self._auth_method != "anonymous":
            try:
                opts = dict(self._common_opts)
                if opts_override:
                    opts.update(opts_override)
                result = self._execute_ydl(url, opts, download)
                elapsed = time.time() - start
                self._log_extraction(url, "yt-dlp", True, elapsed, result)
                return result
            except Exception as e:
                if not self._is_retryable(e):
                    raise
                last_error = e
                logger.debug(f"Layer1 (cookies) falhou: {str(e)[:100]}")

        # Tenta cada estratégia de cliente
        for i, strategy in enumerate(self._client_strategies):
            try:
                self._rotate_headers()
                opts = dict(self._common_opts)
                opts["extractor_args"] = strategy["extractor_args"]
                opts["http_headers"] = dict(self._current_headers)
                if opts_override:
                    opts.update(opts_override)

                # Tenta proxy diferente a cada estratégia
                proxy = self._proxy_pool.get_proxy()
                if proxy:
                    opts["proxy"] = proxy

                result = self._execute_ydl(url, opts, download)
                elapsed = time.time() - start
                self._log_extraction(url, "yt-dlp", True, elapsed, result)
                return result
            except Exception as e:
                last_error = e
                if not self._is_retryable(e):
                    raise
                logger.debug(f"Layer1 strategy {i+1} falhou: {str(e)[:100]}")
                time.sleep(random.uniform(0.3, 0.8))

        if last_error:
            elapsed = time.time() - start
            self._log_extraction(url, "yt-dlp", False, elapsed, None, str(last_error)[:200])
            raise last_error
        return None

    def _execute_ydl(self, url: str, opts: Dict, download: bool = False) -> Dict:
        """Executa yt-dlp com as opções fornecidas."""
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=download)

    def _is_retryable(self, error: Exception) -> bool:
        """Verifica se o erro é recuperável com outra estratégia."""
        msg = str(error).lower()
        patterns = [
            "sign in", "signin", "bot", "captcha", "unavailable",
            "rate limit", "too many requests", "429", "403",
            "http error 403", "http error 429",
            "requested format not available", "no video formats found",
            "this video is unavailable", "age restriction", "age-gate",
            "confirm your age", "video unavailable",
            "playback on other websites", "private video",
            "connection", "timeout", "timed out",
        ]
        return any(p in msg for p in patterns)

    # ──────────────────────────────────────────────────────────────
    # Layer 2: Mobile Page Parsing
    # ──────────────────────────────────────────────────────────────

    def _extract_layer2(self, url: str) -> Optional[Dict]:
        """
        Camada 2: Parsing manual da página mobile (m.youtube.com).
        Usa regex para extrair initialData e initialPlayerResponse do HTML.
        """
        start = time.time()
        video_id = self._extract_video_id(url)
        if not video_id:
            return None

        mobile_url = f"https://m.youtube.com/watch?v={video_id}"
        logger.debug(f"Layer2: parsing {mobile_url}")

        try:
            self._apply_rate_limit()
            self._rotate_headers()

            # Requisição para página mobile
            resp = requests.get(
                mobile_url,
                headers=dict(self._current_headers),
                timeout=self.LAYER2_TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()
            html = resp.text

            # Extrai ytInitialData via regex
            initial_data = self._extract_json_from_html(
                html, r'ytInitialData\s*=\s*({.*?});'
            )

            # Extrai ytInitialPlayerResponse via regex
            player_response = self._extract_json_from_html(
                html, r'ytInitialPlayerResponse\s*=\s*({.*?});'
            )

            if not player_response:
                # Tenta padrão alternativo
                player_response = self._extract_json_from_html(
                    html, r'window\[["\']ytInitialPlayerResponse["\']\]\s*=\s*({.*?});'
                )

            if not player_response:
                elapsed = time.time() - start
                self._log_extraction(url, "mobile", False, elapsed, None,
                                     "player_response não encontrado no HTML")
                return None

            # Converte para dicionário
            info = self._parse_mobile_player_response(player_response, video_id)

            if info:
                elapsed = time.time() - start
                self._log_extraction(url, "mobile", True, elapsed, info)
                return info

            elapsed = time.time() - start
            self._log_extraction(url, "mobile", False, elapsed, None,
                                 "Falha ao parsear player_response")
            return None

        except requests.RequestException as e:
            elapsed = time.time() - start
            self._log_extraction(url, "mobile", False, elapsed, None, str(e)[:200])
            logger.warning(f"Layer2 request falhou: {e}")
            return None
        except Exception as e:
            elapsed = time.time() - start
            self._log_extraction(url, "mobile", False, elapsed, None, str(e)[:200])
            logger.warning(f"Layer2 parsing falhou: {e}")
            return None

    def _extract_json_from_html(self, html: str, pattern: str) -> Optional[Dict]:
        """
        Extrai JSON do HTML usando regex.
        Mais resiliente que depender de atributos fixos.
        """
        try:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                json_str = match.group(1)
                return json.loads(json_str)
        except (json.JSONDecodeError, IndexError) as e:
            logger.debug(f"Regex JSON extraction falhou: {e}")
        return None

    def _parse_mobile_player_response(self, data: Dict, video_id: str) -> Optional[Dict]:
        """
        Converte player_response mobile para formato padronizado.
        """
        try:
            # Extrai detalhes do vídeo
            video_details = data.get("videoDetails", {})
            if not video_details:
                return None

            title = video_details.get("title", "Sem título")
            channel = video_details.get("author", "Desconhecido")
            channel_id = video_details.get("channelId", "")
            duration_str = video_details.get("lengthSeconds", "0")
            try:
                duration = int(float(duration_str))
            except (ValueError, TypeError):
                duration = 0

            view_count = int(video_details.get("viewCount", 0) or 0)
            is_private = video_details.get("isPrivate", False)
            is_age_restricted = video_details.get("isAgeRestricted", False)
            is_live = video_details.get("isLiveContent", False)

            description = video_details.get("shortDescription", "")
            thumbnail = video_details.get("thumbnail", {}).get("thumbnails", [{}])[0].get("url", "")
            if not thumbnail:
                thumbnail = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

            # Extrai formatos do streamingData
            streaming_data = data.get("streamingData", {})
            formats = streaming_data.get("formats", [])
            adaptive_formats = streaming_data.get("adaptiveFormats", [])

            all_formats_raw = formats + adaptive_formats

            # Converte para FormatInfo
            format_infos: List[FormatInfo] = []
            for f in all_formats_raw:
                itag = str(f.get("itag", ""))
                fmt = FormatInfo(
                    itag=itag,
                    ext=f.get("mimeType", "").split(";")[0].split("/")[-1] if f.get("mimeType") else "unknown",
                    width=f.get("width"),
                    height=f.get("height"),
                    fps=f.get("fps"),
                    bitrate=f.get("bitrate"),
                    abr=f.get("averageBitrate"),
                    codec=f.get("codecs", ""),
                    vcodec=f.get("vcodec", ""),
                    acodec=f.get("acodec", ""),
                    filesize=f.get("contentLength"),
                    url=f.get("url", ""),
                    is_audio=f.get("vcodec") == "none" or f.get("audioQuality") is not None,
                    is_video=f.get("acodec") == "none" or f.get("width") is not None,
                    has_audio=f.get("acodec") not in (None, "none"),
                    has_video=f.get("vcodec") not in (None, "none"),
                    quality_label=f.get("qualityLabel"),
                )
                # Preenche metadados de itag conhecida
                if itag in AUDIO_ITAGS:
                    meta = AUDIO_ITAGS[itag]
                    fmt.abr = fmt.abr or meta["abr"]
                    fmt.codec = fmt.codec or meta["codec"]
                    fmt.is_audio = True
                if itag in VIDEO_ITAGS:
                    meta = VIDEO_ITAGS[itag]
                    fmt.height = fmt.height or meta["height"]
                    fmt.fps = fmt.fps or meta["fps"]
                    fmt.codec = fmt.codec or meta["codec"]
                    fmt.is_video = True
                format_infos.append(fmt)

            # Separa áudio e vídeo
            audio_formats = [f for f in format_infos if f.is_audio and f.has_audio]
            video_formats = [f for f in format_infos if f.is_video and f.has_video]

            # Melhor áudio (maior bitrate)
            best_audio = None
            if audio_formats:
                best_audio = max(audio_formats, key=lambda f: f.abr or 0)

            # Melhor vídeo (maior resolução)
            best_video = None
            if video_formats:
                best_video = max(video_formats, key=lambda f: f.height or 0)

            # Captions
            captions_data = data.get("captions", {}).get("playerCaptionsTracklistRenderer", {})
            captions = {}
            for track in captions_data.get("captionTracks", []):
                lang = track.get("languageCode", "unknown")
                captions[lang] = {
                    "name": track.get("name", {}).get("simpleText", lang),
                    "url": track.get("baseUrl", ""),
                }

            return {
                "id": video_id,
                "title": title,
                "channel": channel,
                "channel_id": channel_id,
                "duration": duration,
                "duration_str": self._format_duration(duration),
                "thumbnail": thumbnail,
                "description": description,
                "view_count": view_count,
                "is_private": is_private,
                "is_age_restricted": is_age_restricted,
                "is_live": is_live,
                "formats": format_infos,
                "audio_formats": audio_formats,
                "video_formats": video_formats,
                "best_audio": best_audio,
                "best_video": best_video,
                "captions": captions,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "_source": "mobile",
            }

        except Exception as e:
            logger.warning(f"Erro ao parsear mobile player_response: {e}")
            return None

    # ──────────────────────────────────────────────────────────────
    # Layer 3: Emergency
    # ──────────────────────────────────────────────────────────────

    def _extract_layer3(self, url: str) -> Optional[Dict]:
        """
        Camada 3 (Emergency): Fallback para API externa ou parsing DASH.
        Tenta múltiplas fontes alternativas.
        """
        start = time.time()
        video_id = self._extract_video_id(url)
        if not video_id:
            return None

        logger.info(f"Layer3 (emergency): tentando fallbacks para {video_id}")

        # Estratégia 3.1: Tenta via invidious.snopyta.org (API pública)
        try:
            result = self._try_invidious_api(video_id)
            if result:
                elapsed = time.time() - start
                self._log_extraction(url, "emergency", True, elapsed, result)
                return result
        except Exception as e:
            logger.debug(f"Layer3 invidious falhou: {e}")

        # Estratégia 3.2: Tenta via youtube.com/oembed
        try:
            result = self._try_oembed_api(video_id)
            if result:
                elapsed = time.time() - start
                self._log_extraction(url, "emergency", True, elapsed, result)
                return result
        except Exception as e:
            logger.debug(f"Layer3 oembed falhou: {e}")

        # Estratégia 3.3: Tenta DASH manifest direto
        try:
            result = self._try_dash_manifest(video_id)
            if result:
                elapsed = time.time() - start
                self._log_extraction(url, "emergency", True, elapsed, result)
                return result
        except Exception as e:
            logger.debug(f"Layer3 DASH falhou: {e}")

        elapsed = time.time() - start
        self._log_extraction(url, "emergency", False, elapsed, None,
                             "Todos os fallbacks de emergência falharam")
        return None

    def _try_invidious_api(self, video_id: str) -> Optional[Dict]:
        """Tenta extrair via Invidious API pública."""
        instances = [
            "https://invidious.snopyta.org",
            "https://yewtu.be",
            "https://inv.riverside.rocks",
        ]
        for instance in instances:
            try:
                api_url = f"{instance}/api/v1/videos/{video_id}"
                resp = requests.get(api_url, timeout=10,
                                    headers={"User-Agent": random.choice(USER_AGENTS)})
                if resp.status_code == 200:
                    data = resp.json()
                    return self._parse_invidious_response(data, video_id)
            except Exception:
                continue
        return None

    def _parse_invidious_response(self, data: Dict, video_id: str) -> Dict:
        """Converte resposta Invidious para formato padronizado."""
        title = data.get("title", "Sem título")
        author = data.get("author", "Desconhecido")
        duration = data.get("lengthSeconds", 0)
        view_count = data.get("viewCount", 0)
        description = data.get("description", "")
        thumbnail = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"

        # Formatos
        format_infos: List[FormatInfo] = []
        for fmt in data.get("formatStreams", []):
            fi = FormatInfo(
                itag=str(fmt.get("itag", "")),
                ext=fmt.get("ext", "unknown"),
                width=fmt.get("resolution", "").split("x")[0] if "x" in fmt.get("resolution", "") else None,
                height=fmt.get("resolution", "").split("x")[1] if "x" in fmt.get("resolution", "") else None,
                bitrate=fmt.get("bitrate"),
                url=fmt.get("url", ""),
                is_audio="audio" in fmt.get("type", "").lower(),
                is_video="video" in fmt.get("type", "").lower(),
                has_audio="audio" in fmt.get("type", "").lower(),
                has_video="video" in fmt.get("type", "").lower(),
            )
            format_infos.append(fi)

        # Áudio adaptativo
        audio_formats: List[FormatInfo] = []
        for af in data.get("adaptiveFormats", []):
            if "audio" in af.get("type", "").lower():
                fi = FormatInfo(
                    itag=str(af.get("itag", "")),
                    ext=af.get("ext", "unknown"),
                    abr=af.get("bitrate"),
                    url=af.get("url", ""),
                    is_audio=True,
                    has_audio=True,
                )
                audio_formats.append(fi)
                format_infos.append(fi)

        best_audio = max(audio_formats, key=lambda f: f.abr or 0) if audio_formats else None

        return {
            "id": video_id,
            "title": title,
            "channel": author,
            "duration": duration,
            "duration_str": self._format_duration(duration),
            "thumbnail": thumbnail,
            "description": description,
            "view_count": view_count,
            "formats": format_infos,
            "audio_formats": audio_formats,
            "video_formats": [],
            "best_audio": best_audio,
            "best_video": None,
            "captions": {},
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "_source": "emergency_invidious",
        }

    def _try_oembed_api(self, video_id: str) -> Optional[Dict]:
        """Tenta extrair metadados via oEmbed API."""
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        resp = requests.get(url, timeout=10,
                            headers={"User-Agent": random.choice(USER_AGENTS)})
        if resp.status_code == 200:
            data = resp.json()
            return {
                "id": video_id,
                "title": data.get("title", "Sem título"),
                "channel": data.get("author_name", "Desconhecido"),
                "channel_id": data.get("author_url", "").split("/")[-1] if data.get("author_url") else None,
                "duration": 0,
                "duration_str": "00:00",
                "thumbnail": data.get("thumbnail_url", f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"),
                "description": "",
                "view_count": 0,
                "formats": [],
                "audio_formats": [],
                "video_formats": [],
                "best_audio": None,
                "best_video": None,
                "captions": {},
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "_source": "emergency_oembed",
            }
        return None

    def _try_dash_manifest(self, video_id: str) -> Optional[Dict]:
        """Tenta extrair via DASH manifest (caso raro)."""
        # Nota: DASH manifest geralmente requer signature decoding
        # Este é um fallback básico
        dash_url = f"https://manifest.googlevideo.com/api/manifest/dash/yt/{video_id}"
        try:
            resp = requests.get(dash_url, timeout=10,
                                headers={"User-Agent": random.choice(USER_AGENTS)})
            if resp.status_code == 200:
                # Parse básico do XML para extrair informações
                soup = BeautifulSoup(resp.text, "lxml")
                title_tag = soup.find("title")
                title = title_tag.text if title_tag else "Sem título"
                return {
                    "id": video_id,
                    "title": title,
                    "channel": "Desconhecido",
                    "duration": 0,
                    "duration_str": "00:00",
                    "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                    "description": "",
                    "view_count": 0,
                    "formats": [],
                    "audio_formats": [],
                    "video_formats": [],
                    "best_audio": None,
                    "best_video": None,
                    "captions": {},
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "_source": "emergency_dash",
                }
        except Exception:
            pass
        return None

    # ──────────────────────────────────────────────────────────────
    # Extração Híbrida Principal
    # ──────────────────────────────────────────────────────────────

    def extract_info(self, url: str, use_cache: bool = True) -> Dict:
        """
        Extrai informações do vídeo usando arquitetura híbrida de 3 camadas.

        Args:
            url: URL do YouTube
            use_cache: Se deve usar cache

        Returns:
            Dicionário com metadados e formatos
        """
        # Cache
        if use_cache:
            cache_key = compute_cache_key("info", url)
            cached = self._info_cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit para {url[:50]}...")
                return cached

        self._apply_rate_limit()
        self._rotate_headers()

        # ── Layer 1: yt-dlp ──
        try:
            logger.info(f"Layer1 (yt-dlp): extraindo {url[:60]}...")
            raw_info = self._extract_layer1(url)
            if raw_info:
                result = self._normalize_info(raw_info, url, "yt-dlp")
                if use_cache:
                    self._info_cache.set(cache_key, result)
                return result
        except Exception as e:
            logger.warning(f"Layer1 falhou: {str(e)[:100]}")

        # ── Layer 2: Mobile Page ──
        try:
            logger.info(f"Layer2 (mobile): extraindo {url[:60]}...")
            mobile_info = self._extract_layer2(url)
            if mobile_info:
                result = self._normalize_info(mobile_info, url, "mobile")
                if use_cache:
                    self._info_cache.set(cache_key, result)
                return result
        except Exception as e:
            logger.warning(f"Layer2 falhou: {str(e)[:100]}")

        # ── Layer 3: Emergency ──
        try:
            logger.info(f"Layer3 (emergency): extraindo {url[:60]}...")
            emergency_info = self._extract_layer3(url)
            if emergency_info:
                result = self._normalize_info(emergency_info, url, "emergency")
                if use_cache:
                    self._info_cache.set(cache_key, result)
                return result
        except Exception as e:
            logger.warning(f"Layer3 falhou: {str(e)[:100]}")

        raise Exception(f"Todas as 3 camadas falharam para {url}")

    def _normalize_info(self, raw: Dict, url: str, source: str) -> Dict:
        """
        Normaliza o resultado de qualquer camada para formato padronizado.
        """
        # Se já veio normalizado (mobile/emergency) - tem audio_formats como lista
        if ("audio_formats" in raw and isinstance(raw.get("audio_formats"), list)
                and "formats" in raw and isinstance(raw.get("formats"), list)):
            # Converte FormatInfo objects para dict se necessário
            formats = raw.get("formats", [])
            audio_formats = raw.get("audio_formats", [])
            video_formats = raw.get("video_formats", [])

            best_audio = raw.get("best_audio")
            best_video = raw.get("best_video")

            return {
                "id": raw.get("id", ""),
                "title": raw.get("title", "Sem título"),
                "channel": raw.get("channel", "Desconhecido"),
                "channel_id": raw.get("channel_id"),
                "duration": raw.get("duration", 0),
                "duration_str": raw.get("duration_str", self._format_duration(raw.get("duration", 0))),
                "thumbnail": raw.get("thumbnail", ""),
                "description": (raw.get("description") or "")[:500],
                "view_count": raw.get("view_count", 0),
                "like_count": raw.get("like_count", 0),
                "upload_date": raw.get("upload_date", ""),
                "categories": raw.get("categories", []),
                "tags": raw.get("tags", [])[:20],
                "is_live": raw.get("is_live", False),
                "is_age_restricted": raw.get("is_age_restricted", False),
                "is_private": raw.get("is_private", False),
                "formats": [f.to_dict() if isinstance(f, FormatInfo) else f for f in formats],
                "audio_formats": [f.to_dict() if isinstance(f, FormatInfo) else f for f in audio_formats],
                "video_formats": [f.to_dict() if isinstance(f, FormatInfo) else f for f in video_formats],
                "best_audio": best_audio.to_dict() if isinstance(best_audio, FormatInfo) else best_audio,
                "best_video": best_video.to_dict() if isinstance(best_video, FormatInfo) else best_video,
                "captions": raw.get("captions", {}),
                "url": url,
                "_source": source,
            }

        # Se veio do yt-dlp (dict raw)
        return self._normalize_ydl_info(raw, url)

    def _normalize_ydl_info(self, info: Dict, url: str) -> Dict:
        """Normaliza resultado do yt-dlp."""
        # Extrai formatos
        raw_formats = info.get("formats", [])
        format_infos: List[FormatInfo] = []
        audio_formats: List[FormatInfo] = []
        video_formats: List[FormatInfo] = []

        for f in raw_formats:
            itag = str(f.get("format_id", ""))
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            is_audio = vcodec == "none" and acodec not in (None, "none")
            is_video = acodec == "none" and vcodec not in (None, "none")
            has_audio = acodec not in (None, "none")
            has_video = vcodec not in (None, "none")

            fi = FormatInfo(
                itag=itag,
                ext=f.get("ext", "unknown"),
                width=f.get("width"),
                height=f.get("height"),
                fps=f.get("fps"),
                bitrate=f.get("tbr"),
                abr=f.get("abr"),
                codec=f.get("codec", ""),
                vcodec=vcodec,
                acodec=acodec,
                filesize=f.get("filesize") or f.get("filesize_approx"),
                url=f.get("url", ""),
                is_audio=is_audio,
                is_video=is_video,
                has_audio=has_audio,
                has_video=has_video,
                quality_label=f.get("format_note", ""),
            )

            # Preenche metadados de itag conhecida
            if itag in AUDIO_ITAGS:
                meta = AUDIO_ITAGS[itag]
                fi.abr = fi.abr or meta["abr"]
                fi.codec = fi.codec or meta["codec"]
            if itag in VIDEO_ITAGS:
                meta = VIDEO_ITAGS[itag]
                fi.height = fi.height or meta["height"]
                fi.fps = fi.fps or meta["fps"]
                fi.codec = fi.codec or meta["codec"]

            format_infos.append(fi)
            if is_audio:
                audio_formats.append(fi)
            if is_video:
                video_formats.append(fi)

        # Melhor áudio
        best_audio = max(audio_formats, key=lambda f: f.abr or 0) if audio_formats else None

        # Melhor vídeo
        best_video = max(video_formats, key=lambda f: f.height or 0) if video_formats else None

        # Thumbnail
        thumbnail = info.get("thumbnail", "")
        if not thumbnail and info.get("thumbnails"):
            thumbs = info["thumbnails"]
            if isinstance(thumbs, list) and thumbs:
                thumbnail = thumbs[0].get("url", "")

        # Channel
        channel = (
            info.get("channel") or
            info.get("uploader") or
            info.get("creator") or
            "Desconhecido"
        )
        if isinstance(channel, dict):
            channel = channel.get("name", "Desconhecido")

        return {
            "id": info.get("id", ""),
            "title": info.get("title", "Sem título"),
            "channel": str(channel),
            "channel_id": info.get("channel_id"),
            "duration": info.get("duration", 0),
            "duration_str": self._format_duration(info.get("duration", 0)),
            "thumbnail": thumbnail,
            "description": (info.get("description") or "")[:500],
            "view_count": info.get("view_count", 0),
            "like_count": info.get("like_count", 0),
            "upload_date": info.get("upload_date", ""),
            "categories": info.get("categories", []),
            "tags": info.get("tags", [])[:20],
            "is_live": info.get("is_live", False),
            "is_age_restricted": info.get("age_limit", 0) > 0,
            "is_private": False,
            "formats": [f.to_dict() for f in format_infos],
            "audio_formats": [f.to_dict() for f in audio_formats],
            "video_formats": [f.to_dict() for f in video_formats],
            "best_audio": best_audio.to_dict() if best_audio else None,
            "best_video": best_video.to_dict() if best_video else None,
            "captions": {},
            "url": url,
            "_source": "yt-dlp",
        }

    # ──────────────────────────────────────────────────────────────
    # API Pública: get_video_info
    # ──────────────────────────────────────────────────────────────

    def get_video_info(self, url: str) -> Dict:
        """
        Retorna metadados completos do vídeo (título, duração, thumbnail, lista de formatos).

        Args:
            url: URL do YouTube

        Returns:
            Dicionário com metadados e todos os formatos disponíveis
        """
        return self.extract_info(url, use_cache=True)

    # ──────────────────────────────────────────────────────────────
    # API Pública: download_video
    # ──────────────────────────────────────────────────────────────

    def download_video(self, url: str, resolution: str = "1080p",
                       output_path: Optional[str] = None) -> str:
        """
        Baixa vídeo na resolução especificada com mesclagem automática de áudio.

        Para resoluções >= 1080p (que geralmente não têm áudio),
        baixa automaticamente a melhor stream de áudio e mescla via FFmpeg.

        Args:
            url: URL do YouTube
            resolution: Resolução desejada (144p, 360p, 720p, 1080p, 4K, 8K)
            output_path: Diretório de saída (opcional)

        Returns:
            Caminho do arquivo .mp4 final
        """
        output_dir = output_path or self.download_dir
        os.makedirs(output_dir, exist_ok=True)

        # Obtém info com formatos
        info = self.extract_info(url, use_cache=True)
        title = info.get("title", "video_sem_titulo")
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", title)[:100]

        # Determina altura alvo
        target_height = RESOLUTION_MAP.get(resolution, 1080)

        # Encontra melhor formato de vídeo para a resolução alvo
        video_formats = info.get("video_formats", [])
        if not video_formats:
            raise Exception(f"Nenhum formato de vídeo encontrado para {url}")

        # Filtra por altura <= target, pega o melhor
        matching = [f for f in video_formats if f.get("height", 0) <= target_height]
        if not matching:
            matching = video_formats

        best_video = max(matching, key=lambda f: (f.get("height", 0), f.get("fps", 30)))

        # Encontra melhor áudio
        audio_formats = info.get("audio_formats", [])
        best_audio = max(audio_formats, key=lambda f: f.get("abr", 0)) if audio_formats else None

        video_url = best_video.get("url", "")
        if not video_url:
            raise Exception(f"URL de stream de vídeo não disponível para itag {best_video.get('itag')}")

        output_file = os.path.join(output_dir, f"{safe_title}.mp4")

        # Verifica se o vídeo já tem áudio embutido
        video_has_audio = best_video.get("has_audio", False)
        video_acodec = best_video.get("acodec", "none")

        if video_has_audio and video_acodec not in (None, "none"):
            # Vídeo já tem áudio - download direto
            logger.info(f"Vídeo {best_video.get('itag')} já tem áudio embutido. Download direto.")
            self._download_stream(video_url, output_file)
        else:
            # Vídeo sem áudio (comum em 1080p+) - precisa mesclar
            if not best_audio or not best_audio.get("url"):
                raise Exception("Vídeo sem áudio e nenhuma stream de áudio disponível para mesclagem")

            audio_url = best_audio["url"]
            logger.info(f"Vídeo sem áudio. Mesclando vídeo + áudio via FFmpeg...")
            self._download_and_merge(video_url, audio_url, output_file, best_audio.get("ext", "m4a"))

        # Verifica resultado
        if os.path.exists(output_file) and os.path.getsize(output_file) > 1024:
            size_mb = os.path.getsize(output_file) / (1024 * 1024)
            logger.info(f"Download concluído: {output_file} ({size_mb:.2f} MB)")
            return output_file
        else:
            raise Exception(f"Arquivo de saída não encontrado ou vazio: {output_file}")

    def _download_stream(self, stream_url: str, output_path: str):
        """Download direto de uma stream URL."""
        import requests
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        resp = requests.get(stream_url, headers=headers, stream=True, timeout=120)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    def _download_and_merge(self, video_url: str, audio_url: str,
                            output_path: str, audio_ext: str = "m4a"):
        """
        Baixa vídeo e áudio separadamente e mescla via FFmpeg.
        """
        import requests
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        # Cria arquivos temporários
        tmp_video = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp_video_path = tmp_video.name
        tmp_video.close()

        tmp_audio = tempfile.NamedTemporaryFile(suffix=f".{audio_ext}", delete=False)
        tmp_audio_path = tmp_audio.name
        tmp_audio.close()

        try:
            # Download vídeo
            logger.info("  Download stream de vídeo...")
            resp_v = requests.get(video_url, headers=headers, stream=True, timeout=120)
            resp_v.raise_for_status()
            with open(tmp_video_path, "wb") as f:
                for chunk in resp_v.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # Download áudio
            logger.info("  Download stream de áudio...")
            resp_a = requests.get(audio_url, headers=headers, stream=True, timeout=120)
            resp_a.raise_for_status()
            with open(tmp_audio_path, "wb") as f:
                for chunk in resp_a.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # Mescla via FFmpeg
            logger.info("  Mesclando via FFmpeg...")
            cmd = [
                "ffmpeg", "-y",
                "-i", tmp_video_path,
                "-i", tmp_audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                output_path,
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                raise Exception(f"FFmpeg merge falhou: {result.stderr[:200]}")

        finally:
            # Limpa temporários
            for tmp_path in [tmp_video_path, tmp_audio_path]:
                try:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except Exception:
                    pass

    # ──────────────────────────────────────────────────────────────
    # API Pública: download_audio
    # ──────────────────────────────────────────────────────────────

    def download_audio(self, url: str, bitrate: str = "high",
                       output_path: Optional[str] = None,
                       format: str = "mp3",
                       filename: Optional[str] = None) -> str:
        """
        Baixa apenas o áudio em MP3/M4A ou formato original.

        Args:
            url: URL do YouTube
            bitrate: Qualidade ('high'=320kbps, 'medium'=192kbps, 'low'=128kbps)
            output_path: Diretório de saída (opcional)
            format: Formato de saída ('mp3', 'm4a' ou 'original')
            filename: Nome personalizado do arquivo (sem extensão, opcional)

        Returns:
            Caminho do arquivo de áudio
        """
        output_dir = output_path or self.download_dir
        os.makedirs(output_dir, exist_ok=True)

        # Mapa de bitrate
        bitrate_map = {
            "high": 320,
            "medium": 192,
            "low": 128,
        }
        target_bitrate = bitrate_map.get(bitrate, 192)

        # Obtém info
        info = self.extract_info(url, use_cache=True)
        title = info.get("title", "audio_sem_titulo")
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", title)[:100]

        # Usa filename personalizado se fornecido
        base_name = filename if filename else safe_title
        base_name = re.sub(r'[<>:"/\\|?*]', "_", base_name)[:100]

        # Encontra melhor áudio
        audio_formats = info.get("audio_formats", [])
        if not audio_formats:
            raise Exception("Nenhum formato de áudio disponível")

        # Prioriza maior bitrate
        best_audio = max(audio_formats, key=lambda f: f.get("abr", 0) or 0)
        audio_url = best_audio.get("url", "")
        if not audio_url:
            raise Exception("URL de stream de áudio não disponível")

        audio_ext = best_audio.get("ext", "m4a")

        # ── Formato "original": baixa sem conversão ──
        if format == "original":
            output_file = os.path.join(output_dir, f"{base_name}.{audio_ext}")
            self._download_stream(audio_url, output_file)
        elif format == "m4a" and audio_ext == "m4a":
            # Download direto (já é m4a)
            output_file = os.path.join(output_dir, f"{base_name}.{format}")
            self._download_stream(audio_url, output_file)
        else:
            # Precisa converter via FFmpeg
            output_file = os.path.join(output_dir, f"{base_name}.{format}")
            tmp_audio = tempfile.NamedTemporaryFile(suffix=f".{audio_ext}", delete=False)
            tmp_path = tmp_audio.name
            tmp_audio.close()

            try:
                # Download do stream original
                self._download_stream(audio_url, tmp_path)

                # Converte via FFmpeg
                if format == "mp3":
                    codec = "libmp3lame"
                else:
                    codec = "aac"

                cmd = [
                    "ffmpeg", "-y",
                    "-i", tmp_path,
                    "-c:a", codec,
                    "-b:a", f"{target_bitrate}k",
                    "-vn",
                    output_file,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if result.returncode != 0:
                    raise Exception(f"FFmpeg conversão falhou: {result.stderr[:200]}")
            finally:
                try:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except Exception:
                    pass

        # Verifica resultado
        if os.path.exists(output_file) and os.path.getsize(output_file) > 1024:
            size_mb = os.path.getsize(output_file) / (1024 * 1024)
            logger.info(f"Áudio baixado: {output_file} ({size_mb:.2f} MB)")
            return output_file
        else:
            raise Exception(f"Arquivo de áudio não encontrado: {output_file}")

    # ──────────────────────────────────────────────────────────────
    # API Pública: get_audio_stream_url
    # ──────────────────────────────────────────────────────────────

    def get_audio_stream_url(self, url: str) -> Tuple[str, str]:
        """
        Obtém URL direta da melhor stream de áudio.

        Returns:
            Tupla (url_stream, titulo)
        """
        # Cache
        cache_key = compute_cache_key("stream", url)
        cached = self._stream_cache.get(cache_key)
        if cached:
            return cached

        info = self.extract_info(url, use_cache=True)
        title = info.get("title", "Sem título")

        audio_formats = info.get("audio_formats", [])
        if not audio_formats:
            raise Exception("Nenhum formato de áudio disponível")

        best = max(audio_formats, key=lambda f: f.get("abr", 0) or 0)
        stream_url = best.get("url", "")
        if not stream_url:
            raise Exception("URL de stream de áudio não disponível")

        result = (stream_url, title)
        self._stream_cache.set(cache_key, result)
        return result

    # ──────────────────────────────────────────────────────────────
    # Search
    # ──────────────────────────────────────────────────────────────

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Busca vídeos/playlists no YouTube.

        Args:
            query: Termo de busca
            max_results: Máximo de resultados

        Returns:
            Lista de resultados
        """
        cache_key = f"search:{query}:{max_results}"
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return cached

        self._apply_rate_limit()
        self._rotate_headers()

        results: List[Dict] = []
        search_query = f"ytsearch{max_results}:{query}"

        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "http_headers": dict(self._current_headers),
        }
        opts.update(self._cookies_opts)

        proxy = self._proxy_pool.get_proxy()
        if proxy:
            opts["proxy"] = proxy

        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
            if info and "entries" in info:
                results = self._parse_search_results(info["entries"])
        except Exception as e:
            logger.warning(f"Search falhou, tentando fallback: {e}")
            # Fallback 1: tenta sem headers e com cliente específico
            try:
                fallback_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": True,
                    "extractor_args": {
                        "youtube": {"player_client": ["android", "ios"]}
                    },
                }
                fallback_opts.update(self._cookies_opts)
                with YoutubeDL(fallback_opts) as ydl:
                    info = ydl.extract_info(search_query, download=False)
                if info and "entries" in info:
                    results = self._parse_search_results(info["entries"])
            except Exception as e2:
                logger.warning(f"Search fallback 1 falhou: {e2}")
                # Fallback 2: scraping direto da página HTML do YouTube
                try:
                    results = self._search_fallback_html(query, max_results)
                except Exception as e3:
                    raise Exception(f"Erro na busca: {e3}")

        self._search_cache.set(cache_key, results)
        return results

    def _search_fallback_html(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Fallback de busca via scraping direto da página HTML do YouTube.
        Extrai ytInitialData do HTML e parseia os resultados de busca.
        """
        import urllib.parse

        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
        logger.info(f"Search fallback HTML: {search_url}")

        self._apply_rate_limit()
        self._rotate_headers()

        headers = dict(self._current_headers)
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

        resp = requests.get(
            search_url,
            headers=headers,
            timeout=self.LAYER2_TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text

        # Extrai ytInitialData do HTML
        initial_data = self._extract_json_from_html(
            html, r'ytInitialData\s*=\s*({.*?});'
        )

        if not initial_data:
            # Tenta padrão alternativo
            initial_data = self._extract_json_from_html(
                html, r'window\[["\']ytInitialData["\']\]\s*=\s*({.*?});'
            )

        if not initial_data:
            logger.warning("ytInitialData não encontrado no HTML de busca")
            return []

        return self._parse_search_html_results(initial_data, max_results)

    def _parse_search_html_results(self, data: Dict, max_results: int) -> List[Dict]:
        """
        Parseia resultados de busca do ytInitialData extraído do HTML.
        """
        results = []

        try:
            # Navega pela estrutura do ytInitialData para encontrar resultados
            contents = (
                data.get("contents", {})
                .get("twoColumnSearchResultsRenderer", {})
                .get("primaryContents", {})
                .get("sectionListRenderer", {})
                .get("contents", [])
            )

            for section in contents:
                item_section = section.get("itemSectionRenderer", {})
                items = item_section.get("contents", [])

                for item in items:
                    if len(results) >= max_results:
                        break

                    # Video renderer
                    video_renderer = item.get("videoRenderer", {})
                    if video_renderer:
                        video_id = video_renderer.get("videoId", "")
                        if not video_id:
                            continue

                        # Título
                        title_obj = video_renderer.get("title", {})
                        title = ""
                        for run in title_obj.get("runs", []):
                            title += run.get("text", "")
                        if not title:
                            title = title_obj.get("simpleText", "Sem título")

                        # Canal
                        channel_renderer = (
                            video_renderer.get("ownerText", {})
                            .get("runs", [{}])[0]
                        )
                        channel = channel_renderer.get("text", "Desconhecido")

                        # Duração
                        duration_str = ""
                        duration_seconds = 0
                        length_section = video_renderer.get("lengthText", {})
                        if length_section:
                            duration_str = length_section.get("simpleText", "")
                            # Converte "5:30" para segundos
                            try:
                                parts = duration_str.split(":")
                                if len(parts) == 2:
                                    duration_seconds = int(parts[0]) * 60 + int(parts[1])
                                elif len(parts) == 3:
                                    duration_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                            except (ValueError, IndexError):
                                duration_seconds = 0

                        # Views
                        view_count = 0
                        view_section = video_renderer.get("viewCountText", {})
                        if view_section:
                            view_text = view_section.get("simpleText", "") or ""
                            for run in view_section.get("runs", []):
                                view_text += run.get("text", "")
                            # Extrai números do texto (ex: "1.234.567 visualizações")
                            view_match = re.search(r'[\d.]+', view_text.replace(".", ""))
                            if view_match:
                                try:
                                    view_count = int(view_match.group(0))
                                except ValueError:
                                    view_count = 0

                        # Thumbnail
                        thumbnail = ""
                        thumb_renderer = video_renderer.get("thumbnail", {})
                        thumbnails = thumb_renderer.get("thumbnails", [])
                        if thumbnails:
                            # Pega a de maior resolução
                            thumbnail = thumbnails[-1].get("url", "")
                        if not thumbnail:
                            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                        # Badges (live, etc)
                        is_live = False
                        badges = video_renderer.get("badges", [])
                        for badge in badges:
                            badge_text = (
                                badge.get("metadataBadgeRenderer", {})
                                .get("label", "")
                            )
                            if "LIVE" in badge_text.upper():
                                is_live = True

                        video = {
                            "id": video_id,
                            "title": title,
                            "channel": channel,
                            "duration": self._format_duration(duration_seconds),
                            "duration_seconds": duration_seconds,
                            "views": view_count,
                            "type": "video",
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "thumbnail": thumbnail,
                            "is_live": is_live,
                        }
                        results.append(video)
                        continue

                    # Playlist renderer
                    playlist_renderer = item.get("playlistRenderer", {})
                    if playlist_renderer:
                        playlist_id = playlist_renderer.get("playlistId", "")
                        if not playlist_id:
                            continue

                        # Título
                        title_obj = playlist_renderer.get("title", {})
                        title = ""
                        for run in title_obj.get("runs", []):
                            title += run.get("text", "")
                        if not title:
                            title = title_obj.get("simpleText", "Playlist sem nome")

                        # Canal
                        channel_text = ""
                        channel_runs = (
                            playlist_renderer.get("shortBylineText", {})
                            .get("runs", [])
                        )
                        for run in channel_runs:
                            channel_text += run.get("text", "")
                        channel = channel_text or "Desconhecido"

                        # Thumbnail
                        thumbnail = ""
                        thumb_renderer = playlist_renderer.get("thumbnail", {})
                        thumbnails = thumb_renderer.get("thumbnails", [])
                        if thumbnails:
                            thumbnail = thumbnails[-1].get("url", "")

                        # Número de vídeos
                        video_count = 0
                        video_count_str = (
                            playlist_renderer.get("videoCount", "")
                            or playlist_renderer.get("videoCountText", {}).get("runs", [{}])[0].get("text", "0")
                        )
                        try:
                            video_count = int(re.sub(r'\D', '', str(video_count_str)))
                        except ValueError:
                            video_count = 0

                        playlist = {
                            "id": playlist_id,
                            "title": title,
                            "channel": channel,
                            "duration": f"{video_count} vídeos",
                            "duration_seconds": 0,
                            "views": 0,
                            "type": "playlist",
                            "url": f"https://www.youtube.com/playlist?list={playlist_id}",
                            "thumbnail": thumbnail,
                            "video_count": video_count,
                        }
                        results.append(playlist)

        except Exception as e:
            logger.warning(f"Erro ao parsear resultados HTML: {e}")

        return results[:max_results]

    def _parse_search_results(self, entries: List) -> List[Dict]:
        """Parseia resultados da busca."""
        results = []
        for entry in entries:
            if not entry:
                continue
            try:
                entry_type = entry.get("ie_key", "") or entry.get("extractor", "")
                is_playlist = "playlist" in entry_type.lower() if entry_type else False

                # Thumbnail
                thumbnail = ""
                raw_thumbs = entry.get("thumbnails") or entry.get("thumbnail", "")
                if isinstance(raw_thumbs, list) and raw_thumbs:
                    for thumb in raw_thumbs:
                        url = thumb.get("url", "")
                        if url and ("maxresdefault" in url or "hqdefault" in url):
                            thumbnail = url
                            break
                    if not thumbnail:
                        thumbnail = raw_thumbs[0].get("url", "")
                elif isinstance(raw_thumbs, str) and raw_thumbs:
                    thumbnail = raw_thumbs

                # Channel
                channel = (
                    entry.get("channel") or
                    entry.get("uploader") or
                    entry.get("creator") or
                    "Desconhecido"
                )
                if isinstance(channel, dict):
                    channel = channel.get("name", "Desconhecido")

                # Duration
                duration_raw = entry.get("duration", 0)
                try:
                    duration_seconds = int(float(duration_raw or 0))
                except (ValueError, TypeError):
                    duration_seconds = 0

                # Views
                views_raw = entry.get("view_count", 0) or 0
                try:
                    views = int(float(views_raw))
                except (ValueError, TypeError):
                    views = 0

                video = {
                    "id": entry.get("id", ""),
                    "title": entry.get("title", "Sem título") or "Sem título",
                    "channel": str(channel),
                    "duration": self._format_duration(duration_seconds),
                    "duration_seconds": duration_seconds,
                    "views": views,
                    "type": "playlist" if is_playlist else "video",
                    "url": (
                        f"https://www.youtube.com/playlist?list={entry.get('id')}"
                        if is_playlist
                        else f"https://www.youtube.com/watch?v={entry.get('id', '')}"
                    ),
                    "thumbnail": thumbnail,
                }
                if video["id"]:
                    results.append(video)
            except Exception as e:
                logger.debug(f"Erro ao processar entry: {e}")
                continue
        return results

    def search_playlists(self, query: str, max_results: int = 5) -> List[Dict]:
        """Busca playlists."""
        results = self.search(query, max_results=max_results * 2)
        return [r for r in results if r["type"] == "playlist"][:max_results]

    def get_playlist_tracks(self, playlist_url: str) -> List[Dict]:
        """Extrai faixas de uma playlist."""
        tracks = []
        if not playlist_url or "list=" not in playlist_url:
            playlist_id = playlist_url.strip()
            if playlist_id and len(playlist_id) > 10:
                playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            else:
                raise ValueError("URL de playlist inválida")

        self._apply_rate_limit()
        self._rotate_headers()

        config: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "playlistend": 50,
        }
        config.update(self._cookies_opts)

        try:
            with YoutubeDL(config) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
            playlist_title = info.get("title", "Playlist sem nome")
            entries = info.get("entries", [])
            for entry in entries:
                if not entry:
                    continue
                try:
                    duration_raw = entry.get("duration", 0)
                    try:
                        duration_seconds = int(float(duration_raw or 0))
                    except (ValueError, TypeError):
                        duration_seconds = 0
                    channel = (
                        entry.get("channel") or
                        entry.get("uploader") or
                        "Desconhecido"
                    )
                    if isinstance(channel, dict):
                        channel = channel.get("name", "Desconhecido")
                    track = {
                        "id": entry.get("id", ""),
                        "title": entry.get("title", "Sem título") or "Sem título",
                        "channel": str(channel),
                        "duration": self._format_duration(duration_seconds),
                        "duration_seconds": duration_seconds,
                        "type": "track",
                        "url": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                        "playlist": playlist_title,
                    }
                    if track["id"]:
                        tracks.append(track)
                except Exception:
                    continue
        except Exception as e:
            raise Exception(f"Erro ao obter faixas da playlist: {e}")

        return tracks

    def download_playlist_audios(self, playlist_url: str,
                                  max_concurrent: int = 3,
                                  progress_callback=None) -> List[str]:
        """Baixa todas as músicas de uma playlist."""
        tracks = self.get_playlist_tracks(playlist_url)
        downloaded_files = []

        if not tracks:
            return downloaded_files

        def download_single(track: Dict) -> Optional[str]:
            try:
                if progress_callback:
                    progress_callback({
                        "status": "downloading",
                        "track": track["title"],
                        "index": tracks.index(track) + 1,
                        "total": len(tracks),
                    })
                filename = f"{track['channel']} - {track['title']}"[:100]
                filepath = self.download_audio(track["url"], filename=filename)
                if progress_callback:
                    progress_callback({
                        "status": "completed",
                        "track": track["title"],
                        "index": tracks.index(track) + 1,
                        "total": len(tracks),
                        "filepath": filepath,
                    })
                return filepath
            except Exception as e:
                if progress_callback:
                    progress_callback({
                        "status": "failed",
                        "track": track["title"],
                        "index": tracks.index(track) + 1,
                        "total": len(tracks),
                        "error": str(e),
                    })
                return None

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {executor.submit(download_single, track): track for track in tracks}
            for future in as_completed(futures):
                try:
                    filepath = future.result()
                    if filepath:
                        downloaded_files.append(filepath)
                except Exception:
                    pass

        return downloaded_files

    # ──────────────────────────────────────────────────────────────
    # Utilitários
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_video_id(url: str) -> Optional[str]:
        """Extrai video ID de qualquer URL do YouTube."""
        patterns = [
            r'(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})',
            r'(?:list=)([a-zA-Z0-9_-]{10,})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _format_duration(seconds) -> str:
        """Converte segundos para HH:MM:SS."""
        try:
            seconds = int(float(seconds or 0))
        except (ValueError, TypeError):
            return "00:00"
        if seconds <= 0:
            return "00:00"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _log_extraction(self, url: str, layer: str, success: bool,
                        response_time: float, info: Optional[Dict] = None,
                        error: Optional[str] = None):
        """Registra log de extração."""
        formats_found = 0
        file_size = None
        if info:
            formats_found = len(info.get("formats", []))
            if info.get("best_audio"):
                file_size = info["best_audio"].get("filesize")

        log_entry = ExtractionLog(
            url=url,
            layer=layer,
            success=success,
            response_time=round(response_time, 3),
            formats_found=formats_found,
            file_size=file_size,
            error=error,
        )
        self._extraction_logs.append(log_entry)

        # Log no logger
        status = "✓" if success else "✗"
        logger.info(f"[{status}] Layer={layer} | Tempo={response_time:.2f}s | "
                     f"Formatos={formats_found} | {url[:60]}")

    def get_extraction_logs(self) -> List[Dict]:
        """Retorna logs de extração."""
        return [log.to_dict() for log in self._extraction_logs]

    def list_downloaded(self) -> List[Dict]:
        """Lista arquivos baixados."""
        downloaded = []
        for ext in ["*.mp3", "*.m4a", "*.mp4", "*.webm"]:
            for f in Path(self.download_dir).glob(ext):
                try:
                    stats = os.stat(f)
                    downloaded.append({
                        "filename": f.name,
                        "path": str(f),
                        "size_mb": round(stats.st_size / (1024 * 1024), 2),
                        "modified": stats.st_mtime,
                        "modified_str": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
                except OSError:
                    continue
        return sorted(downloaded, key=lambda x: x["modified"], reverse=True)

    def clear_cache(self):
        """Limpa todos os caches."""
        self._info_cache.clear()
        self._search_cache.clear()
        self._stream_cache.clear()
        logger.info("Caches limpos")

    @staticmethod
    def format_results(results: List[Dict], show_index: bool = True) -> str:
        """Formata resultados para exibição."""
        if not results:
            return "Nenhum resultado encontrado."

        lines = []
        lines.append("=" * 80)
        lines.append(f"{'RESULTADOS':^80}")
        lines.append("=" * 80)

        for i, item in enumerate(results, 1):
            prefix = f"{i:2d}. " if show_index else ""
            item_type = item.get("type", "video")
            type_badge = "📋 PLAYLIST" if item_type == "playlist" else "🎵 MÚSICA"
            if item_type == "track":
                type_badge = "  🎵 TRACK"

            views = item.get("views", 0) or 0
            try:
                views_str = f"{int(views):,}"
            except (ValueError, TypeError):
                views_str = str(views)

            lines.append("")
            lines.append(f"{prefix}[{type_badge}] {item.get('title', 'Sem título')}")
            lines.append(f"       Canal: {item.get('channel', 'Desconhecido')}")
            lines.append(f"       Duração: {item.get('duration', 'N/A')}   👁 {views_str}")

            if item_type in ("video", "track"):
                lines.append(f"       Ações: [P]lay | [D]ownload")
            elif item_type == "playlist":
                lines.append(f"       Ações: [T]racks (ver faixas) | [DP] Download playlist")

        lines.append("")
        lines.append("=" * 80)
        lines.append("Digite o NÚMERO + LETRA da ação (ex: 1p, 2d, 3t)")
        return "\n".join(lines)

    def __del__(self):
        """Cleanup."""
        if self._temp_cookie_file and os.path.exists(self._temp_cookie_file):
            try:
                os.unlink(self._temp_cookie_file)
            except Exception:
                pass