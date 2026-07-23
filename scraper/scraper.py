"""
Módulo principal do YouTube Scraper.
Motor completo: busca músicas, playlists, download e streaming de áudio.
Usa yt-dlp (não requer API key) com múltiplas estratégias anti-bloqueio,
rate limiting, cache inteligente e fallback progressivo.

Inspirado nas melhores práticas de ferramentas como SnapTube, Muka e yt-dlp.
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
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from yt_dlp import YoutubeDL

logger = logging.getLogger(__name__)


class MemoryCache:
    """
    Cache simples em memória com TTL (time-to-live).
    Evita requisições repetidas para buscas idênticas.
    """

    def __init__(self, ttl_seconds: int = 120):
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
    """Gera uma chave de cache única baseada nos argumentos."""
    raw = str(args) + str(sorted(kwargs.items()))
    return hashlib.md5(raw.encode()).hexdigest()


class YouTubeScraper:
    """
    Classe principal para scraping de áudio do YouTube com múltiplas
    estratégias de fallback, rate limiting e cache inteligente.
    Versão 2.1 - Melhorias de robustez para endpoints /api/download e /api/info
    """

    # Delay mínimo entre requisições (em segundos)
    MIN_REQUEST_DELAY = 1.0
    # Delay máximo entre requisições (jitter aleatório)
    MAX_REQUEST_DELAY = 3.0

    # Timeout para operações de rede (em segundos)
    NETWORK_TIMEOUT = 30

    def __init__(self, download_dir: Optional[str] = None):
        self.download_dir = download_dir or os.path.join(
            os.path.expanduser("~"), "YouTubeMusic"
        )
        os.makedirs(self.download_dir, exist_ok=True)
        self._temp_cookie_file = None

        # Cache de busca (2 minutos de TTL)
        self._search_cache = MemoryCache(ttl_seconds=120)
        # Cache de info de vídeo (10 minutos de TTL)
        self._info_cache = MemoryCache(ttl_seconds=600)

        # Timestamp da última requisição para rate limiting
        self._last_request_time = 0.0

        # Verificar se está rodando em ambiente cloud
        self._is_cloud_env = self._detect_cloud_environment()

        # Configurações para bypass do bloqueio do YouTube
        proxy_url = os.environ.get("YOUTUBE_PROXY", "")
        cookies_browser = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "")
        cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE", "")
        cookies_base64 = os.environ.get("YOUTUBE_COOKIES_BASE64", "")

        # Lista de User-Agents realistas para rotacionar
        self._user_agents = [
            # Chrome Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            # Chrome macOS
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            # Firefox Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
            # Edge Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        ]

        # Headers realistas para evitar detecção
        self._http_headers = self._generate_headers()

        # Configuração base
        self._common_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "http_headers": dict(self._http_headers),
            "extractor_args": {
                "youtube": {
                    "include_dash_manifest": False,
                    "player_client": ["android", "ios"],  # Padrão: clientes mobile
                }
            },
            "extractor_retries": 3,
            "file_access_retries": 3,
            "fragment_retries": 3,
            "retries": 3,
            "skip_unavailable_fragments": True,
            "socket_timeout": self.NETWORK_TIMEOUT,
        }

        # Configurar proxy se fornecido
        if proxy_url:
            self._common_opts["proxy"] = proxy_url
            logger.info(f"Usando proxy: {proxy_url}")

        auth_source = None

        # Tenta usar cookies se disponíveis
        if cookies_browser:
            browser_name = cookies_browser.strip().lower()
            self._common_opts["cookiesfrombrowser"] = browser_name
            auth_source = f"browser ({browser_name})"
            logger.info(f"Usando cookies do navegador: {browser_name}")
        elif cookies_file and os.path.exists(cookies_file):
            self._common_opts["cookiefile"] = cookies_file
            auth_source = f"cookies file ({cookies_file})"
            logger.info(f"Usando arquivo de cookies: {cookies_file}")
        elif cookies_base64:
            try:
                cookies_content = base64.b64decode(cookies_base64).decode('utf-8')
                temp_cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
                temp_cookie_file.write(cookies_content)
                temp_cookie_file.close()
                self._common_opts["cookiefile"] = temp_cookie_file.name
                self._temp_cookie_file = temp_cookie_file.name
                auth_source = "cookies base64 (environment variable)"
                logger.info(f"Usando cookies base64 da variável de ambiente")
            except Exception as e:
                logger.warning(f"Erro ao decodificar cookies base64: {e}")
        if not auth_source:
            auth_source = "client android/ios (sem cookies)"
            logger.info("Usando client android/ios sem cookies. Se falhar, configure YOUTUBE_COOKIES_FILE")

        logger.info(f"Método de autenticação: {auth_source}")

        # Lista de estratégias de cliente para tentar em caso de bloqueio
        self._client_strategies = self._build_client_strategies()

        # Configurações para download de áudio
        self.ydl_opts = {
            **self._common_opts,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "outtmpl": os.path.join(self.download_dir, "%(title)s.%(ext)s"),
            # Concatenação de fragmentos para streams fragmentados
            "concurrent_fragment_downloads": 5,
        }

    def _generate_headers(self) -> Dict[str, str]:
        """Gera headers HTTP realistas com User-Agent aleatório."""
        ua = random.choice(self._user_agents)
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
        }

    def _rotate_user_agent(self):
        """Rotaciona o User-Agent para a próxima requisição."""
        self._http_headers = self._generate_headers()
        self._common_opts["http_headers"] = dict(self._http_headers)
        # Atualiza também nas estratégias que têm http_headers
        for strategy in self._client_strategies:
            if "http_headers" in strategy:
                strategy["http_headers"]["User-Agent"] = self._http_headers["User-Agent"]

    def _apply_rate_limit(self):
        """
        Aplica rate limiting com jitter aleatório entre requisições.
        Essencial para evitar detecção como bot e bloqueio de IP.
        """
        elapsed = time.time() - self._last_request_time
        delay = random.uniform(self.MIN_REQUEST_DELAY, self.MAX_REQUEST_DELAY)
        if elapsed < delay:
            sleep_time = delay - elapsed
            logger.debug(f"Rate limit: aguardando {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def _detect_cloud_environment(self) -> bool:
        """Detecta se está rodando em ambiente cloud."""
        indicators = [
            os.path.exists("/proc/self/cgroup"),
            os.path.exists("/.dockerenv"),
            os.environ.get("RENDER", "") != "",
            os.environ.get("DYNO", "") != "",
            os.environ.get("HEROKU", "") != "",
            os.environ.get("RAILWAY_ENVIRONMENT", "") != "",
            os.environ.get("FLY_APP_NAME", "") != "",
        ]
        return any(indicators)

    def _detect_browser_cookies(self) -> Optional[str]:
        """
        Tenta detectar cookies de navegadores instalados automaticamente.
        Retorna o nome do navegador ou None. Suprime warnings do yt-dlp.
        """
        browsers = ["chrome", "firefox", "edge", "brave", "opera", "chromium", "vivaldi"]
        
        # Suprime logs do yt-dlp durante detecção
        yt_logger = logging.getLogger("yt_dlp")
        old_level = yt_logger.level
        yt_logger.setLevel(logging.CRITICAL + 1)  # Suprime tudo
        
        try:
            for browser in browsers:
                try:
                    test_opts = {
                        "quiet": True,
                        "no_warnings": True,
                        "extract_flat": True,
                        "logger": type('NullLogger', (), {
                            'debug': lambda *a: None,
                            'info': lambda *a: None,
                            'warning': lambda *a: None,
                            'error': lambda *a: None,
                        })(),
                    }
                    with YoutubeDL(test_opts) as ydl:
                        info = ydl.extract_info("ytsearch1:test", download=False)
                        if info:
                            self._common_opts["cookiesfrombrowser"] = browser
                            return browser
                except Exception:
                    continue
        finally:
            yt_logger.setLevel(old_level)
        
        return None

    def _build_client_strategies(self) -> List[Dict]:
        """
        Constrói lista de estratégias de cliente para fallback.
        Quanto mais estratégias, maior a chance de sucesso.
        """
        return [
            # Estratégia 1: android + ios (padrão - mais leve)
            {
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android", "ios"],
                        "include_dash_manifest": False,
                    }
                },
            },
            # Estratégia 2: web client (Safari) - menos detectado como bot
            {
                "extractor_args": {
                    "youtube": {
                        "player_client": ["web_safari"],
                        "include_dash_manifest": False,
                    }
                },
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            },
            # Estratégia 3: android TV - diferente dos clientes comuns
            {
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android_tv"],
                        "include_dash_manifest": False,
                    }
                },
            },
            # Estratégia 4: web embbed (incorporado) - parece tráfego de site
            {
                "extractor_args": {
                    "youtube": {
                        "player_client": ["web_embbed"],
                        "include_dash_manifest": False,
                    }
                },
            },
            # Estratégia 5: web creator - cliente para criadores de conteúdo
            {
                "extractor_args": {
                    "youtube": {
                        "player_client": ["web_creator"],
                        "include_dash_manifest": False,
                    }
                },
            },
            # Estratégia 6: mweb - mobile web
            {
                "extractor_args": {
                    "youtube": {
                        "player_client": ["mweb"],
                        "include_dash_manifest": False,
                    }
                },
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            },
            # Estratégia 7: tv_embedded - Android TV embutido
            {
                "extractor_args": {
                    "youtube": {
                        "player_client": ["tv_embedded"],
                        "include_dash_manifest": False,
                    }
                },
            },
            # Estratégia 8: iOS + tvOS 
            {
                "extractor_args": {
                    "youtube": {
                        "player_client": ["ios", "tvos"],
                        "include_dash_manifest": False,
                    }
                },
                "http_headers": {
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            },
        ]

    def _check_youtube_connectivity(self) -> bool:
        """
        Verifica rapidamente se o YouTube está acessível.
        Usa uma busca mínima para testar conectividade.
        """
        try:
            test_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "socket_timeout": 10,
            }
            with YoutubeDL(test_opts) as ydl:
                ydl.extract_info("ytsearch1:test", download=False)
            return True
        except Exception as e:
            error_str = str(e).lower()
            if "connection" in error_str or "timeout" in error_str or "resolve" in error_str:
                logger.warning(f"YouTube parece inacessível: {e}")
                return False
            # Outros erros podem ser de conteúdo, não conectividade
            return True

    def _should_retry_error(self, error: Exception) -> bool:
        """
        Verifica se o erro é um tipo que vale a pena tentar novamente
        com estratégia diferente (bloqueio, sign in, bot detection, etc).
        """
        error_msg = str(error).lower()
        retryable_patterns = [
            "sign in",
            "signin",
            "bot",
            "captcha",
            "unavailable",
            "rate limit",
            "too many requests",
            "429",
            "403",
            "http error 403",
            "http error 429",
            "requested format not available",
            "no video formats found",
            "this video is unavailable",
            "age restriction",
            "age-gate",
            "confirm your age",
            "video unavailable",
            "playback on other websites",
        ]
        return any(pattern in error_msg for pattern in retryable_patterns)

    def _extract_with_retry(self, url: str, download: bool = False,
                            opts_override: Optional[Dict] = None,
                            use_cache: bool = False) -> Dict:
        """
        Tenta extrair informações com múltiplas estratégias de cliente,
        rate limiting e rotação de User-Agent.

        Args:
            url: URL do YouTube
            download: Se deve baixar o áudio
            opts_override: Opções extras para sobrescrever
            use_cache: Se deve usar cache para esta extração

        Returns:
            Informações extraídas
        """
        # Rate limiting antes de qualquer requisição
        self._apply_rate_limit()

        # Verificar cache se aplicável
        if use_cache and not download:
            cache_key = compute_cache_key(url, opts_override)
            cached = self._info_cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit para {url[:50]}...")
                return cached

        # Se já tem cookies configurados, tenta direto primeiro
        cookies_available = (
            "cookiesfrombrowser" in self._common_opts or
            "cookiefile" in self._common_opts
        )

        if cookies_available:
            base_opts = dict(self._common_opts)
            if opts_override:
                base_opts.update(opts_override)
            try:
                result = self._execute_extraction(url, base_opts, download)
                if use_cache and not download:
                    self._info_cache.set(cache_key, result)
                return result
            except Exception as e:
                if not self._should_retry_error(e):
                    raise
                logger.warning(f"Cookies falharam, tentando estratégias alternativas: {str(e)[:100]}")

        # Tenta cada estratégia de cliente (sempre mantendo cookies)
        last_error = None
        for i, strategy in enumerate(self._client_strategies):
            strategy_opts = dict(self._common_opts)
            # Aplica estratégia
            strategy_opts["extractor_args"] = strategy["extractor_args"]
            if "http_headers" in strategy:
                strategy_opts["http_headers"] = strategy["http_headers"]
            if opts_override:
                strategy_opts.update(opts_override)

            # Rotaciona User-Agent a cada tentativa
            self._rotate_user_agent()
            strategy_opts["http_headers"] = dict(self._http_headers)

            try:
                logger.info(
                    f"Tentando estratégia {i + 1}/{len(self._client_strategies)}: "
                    f"{strategy['extractor_args']['youtube']['player_client']}"
                )
                result = self._execute_extraction(url, strategy_opts, download)
                if use_cache and not download:
                    self._info_cache.set(cache_key, result)
                return result
            except Exception as e:
                last_error = e
                if not self._should_retry_error(e):
                    raise
                logger.warning(
                    f"Estratégia {i + 1} falhou: {str(e)[:100]}"
                )
                # Delay entre estratégias para parecer menos agressivo
                time.sleep(random.uniform(0.5, 1.5))
                continue

        # Se todas falharam, levanta o último erro
        raise last_error or Exception("Todas as estratégias de extração falharam")

    def _execute_extraction(self, url: str, opts: Dict, download: bool = False) -> Dict:
        """
        Executa a extração com as opções fornecidas.
        Trata erros comuns de rede e parsing.
        """
        try:
            with YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=download)
        except Exception as e:
            error_msg = str(e)
            # Trata erro de rede específico
            if "Connection" in error_msg or "connection" in error_msg:
                raise ConnectionError(f"Erro de conexão com o YouTube: {error_msg[:100]}")
            if "timed out" in error_msg or "timeout" in error_msg:
                raise TimeoutError(f"Timeout ao contactar o YouTube: {error_msg[:100]}")
            raise

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Busca músicas/artistas/playlists com cache e retry.
        Retorna vídeos e playlists.

        Args:
            query: Termo de busca
            max_results: Máximo de resultados

        Returns:
            Lista com type='video' ou type='playlist'
        """
        # Verificar cache
        cache_key = f"search:{query}:{max_results}"
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit para busca: '{query}'")
            return cached

        # Rate limiting
        self._apply_rate_limit()
        self._rotate_user_agent()

        results = []
        search_query = f"ytsearch{max_results}:{query}"

        # Tenta busca com opções básicas (mais compatível)
        last_error = None
        base_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "http_headers": dict(self._http_headers),
        }
        # Copia cookies/proxy do common_opts
        if "cookiesfrombrowser" in self._common_opts:
            base_opts["cookiesfrombrowser"] = self._common_opts["cookiesfrombrowser"]
        if "cookiefile" in self._common_opts:
            base_opts["cookiefile"] = self._common_opts["cookiefile"]
        if "proxy" in self._common_opts:
            base_opts["proxy"] = self._common_opts["proxy"]

        try:
            with YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)

            if info and "entries" in info:
                results = self._parse_search_results(info["entries"])

        except Exception as e:
            last_error = e
            logger.debug(f"Busca com opções básicas falhou, tentando fallback: {str(e)[:100]}")

            # Fallback: tenta sem http_headers extras
            try:
                fallback_opts = dict(base_opts)
                fallback_opts.pop("http_headers", None)
                fallback_opts["extractor_args"] = {
                    "youtube": {
                        "player_client": ["android", "ios"],
                    }
                }
                with YoutubeDL(fallback_opts) as ydl:
                    info = ydl.extract_info(search_query, download=False)
                if info and "entries" in info:
                    results = self._parse_search_results(info["entries"])
                    logger.debug(f"Busca fallback funcionou para '{query}'")
            except Exception as e2:
                last_error = e2
                logger.warning(f"Busca fallback também falhou: {str(e2)[:100]}")

        # Se todas as tentativas falharam
        if not results and last_error:
            raise Exception(f"Erro na busca: {str(last_error)}")

        # Salva no cache
        self._search_cache.set(cache_key, results)

        return results

    def _parse_search_results(self, entries: List) -> List[Dict]:
        """
        Parseia os resultados da busca de forma robusta.
        Extrai thumbnails corretamente mesmo com extract_flat.
        """
        results = []

        for entry in entries:
            if not entry:
                continue

            try:
                entry_type = entry.get("ie_key", "") or entry.get("extractor", "")
                is_playlist = "playlist" in entry_type.lower() if entry_type else False

                # Extrair thumbnail de forma robusta
                thumbnail = ""
                raw_thumbnails = entry.get("thumbnails") or entry.get("thumbnail", "")
                if isinstance(raw_thumbnails, list) and raw_thumbnails:
                    for thumb in raw_thumbnails:
                        url = thumb.get("url", "")
                        if url and ("maxresdefault" in url or "hqdefault" in url or "mqdefault" in url):
                            thumbnail = url
                            break
                    if not thumbnail:
                        thumbnail = raw_thumbnails[0].get("url", "")
                elif isinstance(raw_thumbnails, str) and raw_thumbnails:
                    thumbnail = raw_thumbnails

                # Extrair channel/uploader de forma robusta
                channel = (
                    entry.get("channel") or
                    entry.get("uploader") or
                    entry.get("creator") or
                    entry.get("artist") or
                    "Desconhecido"
                )
                if isinstance(channel, dict):
                    channel = channel.get("name", "Desconhecido")

                # Duração
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

                # Só adiciona se tiver ID válido
                if video["id"]:
                    results.append(video)

            except Exception as e:
                logger.debug(f"Erro ao processar entry: {e}")
                continue

        return results

    def search_playlists(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        Busca especificamente por playlists.

        Args:
            query: Termo de busca
            max_results: Máximo de playlists

        Returns:
            Lista de playlists encontradas
        """
        results = self.search(query, max_results=max_results * 2)
        playlists = [r for r in results if r["type"] == "playlist"]
        return playlists[:max_results]

    def get_playlist_tracks(self, playlist_url: str) -> List[Dict]:
        """
        Extrai as faixas individuais de uma playlist com retry.
        Cada faixa é um áudio separado (não um único arquivo).

        Args:
            playlist_url: URL da playlist do YouTube

        Returns:
            Lista de dicionários com cada música da playlist
        """
        tracks = []
        last_error = None

        # Verifica URL
        if not playlist_url or "list=" not in playlist_url:
            # Tenta extrair ID de outros formatos
            playlist_id = playlist_url.strip()
            if playlist_id and len(playlist_id) > 10:
                playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            else:
                raise ValueError("URL de playlist inválida")

        # Rate limiting
        self._apply_rate_limit()
        self._rotate_user_agent()

        # Configurações para tentar
        playlist_configs = [
            {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "playlistend": 50,
            },
            {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "playlistend": 50,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android", "ios"],
                    }
                },
            },
        ]

        for config in playlist_configs:
            try:
                # Copia cookies/proxy
                if "cookiesfrombrowser" in self._common_opts:
                    config["cookiesfrombrowser"] = self._common_opts["cookiesfrombrowser"]
                if "cookiefile" in self._common_opts:
                    config["cookiefile"] = self._common_opts["cookiefile"]
                if "proxy" in self._common_opts:
                    config["proxy"] = self._common_opts["proxy"]

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
                    except Exception as e:
                        logger.debug(f"Erro ao processar track da playlist: {e}")
                        continue

                if tracks:
                    logger.info(f"Playlist '{playlist_title}': {len(tracks)} faixas extraídas")
                    return tracks

            except Exception as e:
                last_error = e
                logger.warning(f"Erro ao extrair playlist: {str(e)[:100]}")
                time.sleep(random.uniform(0.5, 1.5))
                continue

        if last_error:
            raise Exception(f"Erro ao obter faixas da playlist: {str(last_error)}")
        return tracks

    def download_audio(self, video_url: str, filename: Optional[str] = None) -> str:
        """
        Baixa o áudio como MP3 usando stream URL + download direto (mais robusto).

        Args:
            video_url: URL do vídeo
            filename: Nome personalizado (opcional)

        Returns:
            Caminho do arquivo MP3
        """
        try:
            # Primeiro obtém a URL de stream (que funciona)
            stream_url, title = self.get_audio_stream_url(video_url)
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:100]
            
            if filename:
                safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)[:100]
                output_path = os.path.join(self.download_dir, f"{safe_name}.mp3")
            else:
                output_path = os.path.join(self.download_dir, f"{safe_title}.mp3")

            # Download direto da stream URL com requests
            import requests
            headers = {
                "User-Agent": random.choice(self._user_agents),
                "Accept": "*/*",
            }
            
            # Usa proxy se configurado
            proxies = {}
            if "proxy" in self._common_opts:
                proxies = {"http": self._common_opts["proxy"], "https": self._common_opts["proxy"]}

            response = requests.get(stream_url, headers=headers, proxies=proxies, stream=True, timeout=60)
            response.raise_for_status()

            # Salva o arquivo
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # Verifica se o arquivo foi criado
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return output_path
            else:
                raise Exception("Arquivo não foi criado ou está vazio")

        except Exception as e:
            raise Exception(f"Erro ao baixar áudio: {str(e)}")

    def get_audio_stream_url(self, video_url: str) -> Tuple[str, str]:
        """
        Obtém URL direta do stream de áudio com múltiplas estratégias.

        Returns:
            Tupla (url_stream, titulo)
        """
        # Verifica cache
        cache_key = compute_cache_key("stream", video_url)
        cached = self._info_cache.get(cache_key)
        if cached:
            return cached

        self._apply_rate_limit()
        self._rotate_user_agent()

        last_error = None

        # Lista de configurações de streaming para tentar
        stream_configs = [
            # Config 1: android + ios com DASH
            {
                "format": "bestaudio/best",
                "extract_flat": False,
                "quiet": True,
                "no_warnings": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android", "ios"],
                        "include_dash_manifest": True,
                    }
                },
            },
            # Config 2: web_safari
            {
                "format": "bestaudio/best",
                "extract_flat": False,
                "quiet": True,
                "no_warnings": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["web_safari"],
                        "include_dash_manifest": True,
                    }
                },
            },
            # Config 3: android TV
            {
                "format": "bestaudio/best",
                "extract_flat": False,
                "quiet": True,
                "no_warnings": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android_tv"],
                        "include_dash_manifest": True,
                    }
                },
            },
        ]

        for config in stream_configs:
            try:
                # Aplica configurações do _common_opts (proxy, cookies, etc.)
                if "proxy" in self._common_opts:
                    config["proxy"] = self._common_opts["proxy"]
                if "cookiesfrombrowser" in self._common_opts:
                    config["cookiesfrombrowser"] = self._common_opts["cookiesfrombrowser"]
                if "cookiefile" in self._common_opts:
                    config["cookiefile"] = self._common_opts["cookiefile"]

                with YoutubeDL(config) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    title = info.get("title", "Sem título")

                if not info:
                    continue

                # Tenta obter a URL direta do áudio
                audio_url = self._extract_best_audio_url(info)

                if audio_url:
                    result = (audio_url, title)
                    self._info_cache.set(cache_key, result)
                    return result

            except Exception as e:
                last_error = e
                logger.warning(f"Config de stream {stream_configs.index(config) + 1} falhou: {str(e)[:100]}")
                time.sleep(random.uniform(0.5, 1.0))
                continue

        # Se chegou aqui, tenta uma abordagem mais agressiva
        try:
            # Tenta com todas as estratégias de cliente
            info = self._extract_with_retry(video_url, download=False)
            title = info.get("title", "Sem título")
            audio_url = self._extract_best_audio_url(info)

            if audio_url:
                result = (audio_url, title)
                self._info_cache.set(cache_key, result)
                return result
        except Exception as e:
            last_error = e

        raise last_error or Exception("Não foi possível obter URL de áudio para este vídeo")

    def _extract_best_audio_url(self, info: Dict) -> str:
        """
        Extrai a melhor URL de áudio disponível das informações do vídeo.
        Tenta múltiplas fontes em ordem de preferência.
        """
        formats = info.get("formats", [])

        # Priority 1: formato de áudio puro (vcodec=none)
        audio_formats = [
            f for f in formats
            if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")
        ]

        if audio_formats:
            # Pega o de maior bitrate
            best_audio = max(
                audio_formats,
                key=lambda f: f.get("abr", 0) or 0,
            )
            url = best_audio.get("url", "")
            if url:
                return url

        # Priority 2: usa a URL direta do info
        url = info.get("url", "")
        if url:
            return url

        # Priority 3: tenta o primeiro formato disponível com URL
        for f in formats:
            url = f.get("url", "")
            if url:
                return url

        # Priority 4: tenta extrair de adaptive_fmts (formato antigo)
        adaptive_fmts = info.get("adaptive_fmts", [])
        if adaptive_fmts:
            for f in adaptive_fmts:
                url = f.get("url", "")
                if url:
                    return url

        return ""

    def get_video_info(self, video_url: str) -> Dict:
        """
        Obtém informações detalhadas do vídeo com cache e retry robusto.

        Args:
            video_url: URL do vídeo

        Returns:
            Dicionário com informações detalhadas
        """
        # Verifica cache
        cache_key = compute_cache_key("info", video_url)
        cached = self._info_cache.get(cache_key)
        if cached:
            return cached

        self._apply_rate_limit()
        self._rotate_user_agent()

        try:
            info = self._extract_with_retry(video_url, download=False, use_cache=True)

            # Extrai formatos de áudio de forma segura
            audio_formats = []
            for f in info.get("formats", []):
                if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none"):
                    audio_formats.append({
                        "format_id": f.get("format_id"),
                        "ext": f.get("ext"),
                        "filesize": f.get("filesize"),
                        "abr": f.get("abr"),
                    })

            # Extrai thumbnail de forma robusta
            thumbnail = info.get("thumbnail", "")
            if not thumbnail and info.get("thumbnails"):
                thumbnail = info["thumbnails"][0].get("url", "")

            # Extrai channel/uploader
            channel = (
                info.get("channel") or
                info.get("uploader") or
                "Desconhecido"
            )
            if isinstance(channel, dict):
                channel = channel.get("name", "Desconhecido")

            result = {
                "id": info.get("id", ""),
                "title": info.get("title", "Sem título"),
                "channel": str(channel),
                "duration": self._format_duration(info.get("duration", 0)),
                "duration_seconds": info.get("duration", 0),
                "view_count": info.get("view_count", 0),
                "like_count": info.get("like_count", 0),
                "thumbnail": thumbnail,
                "audio_formats": audio_formats,
                "description": (info.get("description") or "")[:300],
                "is_playlist": "playlist" in (info.get("extractor", "") or "").lower(),
                "url": video_url,
                "categories": info.get("categories", []),
                "tags": info.get("tags", [])[:10],  # Limita a 10 tags
                "upload_date": info.get("upload_date", ""),
            }

            self._info_cache.set(cache_key, result)
            return result

        except Exception as e:
            # Fallback: tenta com opções mínimas se falhar
            try:
                logger.warning(f"get_video_info falhou, tentando fallback: {str(e)[:100]}")
                fallback_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "extract_flat": False,
                    "socket_timeout": self.NETWORK_TIMEOUT,
                }
                # Mantém proxy e cookies
                if "proxy" in self._common_opts:
                    fallback_opts["proxy"] = self._common_opts["proxy"]
                if "cookiesfrombrowser" in self._common_opts:
                    fallback_opts["cookiesfrombrowser"] = self._common_opts["cookiesfrombrowser"]
                if "cookiefile" in self._common_opts:
                    fallback_opts["cookiefile"] = self._common_opts["cookiefile"]

                with YoutubeDL(fallback_opts) as ydl:
                    info = ydl.extract_info(video_url, download=False)

                # Retorna info básica mesmo com fallback
                return {
                    "id": info.get("id", ""),
                    "title": info.get("title", "Sem título"),
                    "channel": str(info.get("channel") or info.get("uploader") or "Desconhecido"),
                    "duration": self._format_duration(info.get("duration", 0)),
                    "duration_seconds": info.get("duration", 0),
                    "thumbnail": info.get("thumbnail", ""),
                    "audio_formats": [],
                    "description": "",
                    "is_playlist": False,
                    "url": video_url,
                    "categories": [],
                    "tags": [],
                    "upload_date": info.get("upload_date", ""),
                }
            except Exception as e2:
                raise Exception(f"Erro ao obter info (fallback também falhou): {str(e2)[:100]}")

    def list_downloaded(self) -> List[Dict]:
        """Lista todos os MP3s baixados com informações detalhadas."""
        downloaded = []
        for f in Path(self.download_dir).glob("*.mp3"):
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

    def download_playlist_audios(self, playlist_url: str,
                                  max_concurrent: int = 3,
                                  progress_callback=None) -> List[str]:
        """
        Baixa todas as músicas de uma playlist como arquivos MP3 separados.
        Usa download concorrente para acelerar o processo.

        Args:
            playlist_url: URL da playlist
            max_concurrent: Número máximo de downloads simultâneos
            progress_callback: Função de callback para progresso (recebe dict com status)

        Returns:
            Lista de caminhos dos arquivos baixados
        """
        tracks = self.get_playlist_tracks(playlist_url)
        downloaded_files = []
        failed_tracks = []

        if not tracks:
            logger.warning("Nenhuma faixa encontrada na playlist")
            return downloaded_files

        logger.info(f"Baixando {len(tracks)} músicas da playlist "
                     f"(máx {max_concurrent} concorrentes)")

        def download_single(track: Dict) -> Tuple[Optional[str], Dict, Optional[str]]:
            """Baixa uma única faixa e retorna o resultado."""
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

                return filepath, track, None

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Falha ao baixar '{track['title']}': {error_msg}")
                if progress_callback:
                    progress_callback({
                        "status": "failed",
                        "track": track["title"],
                        "index": tracks.index(track) + 1,
                        "total": len(tracks),
                        "error": error_msg,
                    })
                return None, track, error_msg

        # Download concorrente com ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {executor.submit(download_single, track): track for track in tracks}

            for future in as_completed(futures):
                try:
                    filepath, track, error = future.result()
                    if filepath:
                        downloaded_files.append(filepath)
                        print(f"    ✅ {track['title']}")
                    else:
                        failed_tracks.append((track, error))
                        print(f"    ❌ {track['title']}: {error}")
                except Exception as e:
                    track = futures[future]
                    failed_tracks.append((track, str(e)))
                    print(f"    ❌ {track['title']}: {e}")

        # Relatório final
        success_count = len(downloaded_files)
        fail_count = len(failed_tracks)
        print(f"\n  📊 Playlist concluída: {success_count} baixadas", end="")
        if fail_count > 0:
            print(f", {fail_count} falhas")
        else:
            print(" com sucesso!")

        return downloaded_files

    @staticmethod
    def _format_duration(seconds) -> str:
        """Converte segundos para HH:MM:SS de forma robusta."""
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

    def clear_cache(self):
        """Limpa todos os caches."""
        self._search_cache.clear()
        self._info_cache.clear()
        logger.info("Cache limpo")

    def __del__(self):
        """Limpa arquivo temporário de cookies se existir."""
        if self._temp_cookie_file and os.path.exists(self._temp_cookie_file):
            try:
                os.unlink(self._temp_cookie_file)
            except Exception:
                pass

    @staticmethod
    def format_results(results: List[Dict], show_index: bool = True) -> str:
        """
        Formata resultados com ações [▶] [⬇] inline.

        Args:
            results: Lista de resultados
            show_index: Mostrar índices

        Returns:
            String formatada com ações por item
        """
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

            # Ações disponíveis
            if item_type in ("video", "track"):
                lines.append(f"       Ações: [P]lay | [D]ownload")
            elif item_type == "playlist":
                lines.append(f"       Ações: [T]racks (ver faixas) | [DP] Download playlist")

        lines.append("")
        lines.append("=" * 80)
        lines.append("Digite o NÚMERO + LETRA da ação (ex: 1p, 2d, 3t)")
        return "\n".join(lines)