"""
Serviço para integração com yt-dlp.
Responsável por buscar metadados e baixar áudio do YouTube.
Implementa busca inteligente com detecção de artistas, músicas e playlists.
"""

import asyncio
import os
import re
import hashlib
import uuid
from typing import List, Optional, Tuple
from pathlib import Path
import yt_dlp
from schemas import VideoMetadata, PlaylistMetadata

import subprocess
import json


class YouTubeService:
    """Serviço para interação com YouTube usando yt-dlp.
    
    Recursos principais:
    - Busca inteligente que detecta se o termo é artista, música ou playlist
    - Gera URL de stream para ouvir online (modo listen)
    - Gera URL de download direto do áudio original (modo download)
    - Download e conversão de áudio via servidor (modo server)
    - Suporte a playlists com download em lote
    - Baseado no funcionamento do SanpTune para experiência otimizada
    """
    
    # Lista de palavras comuns que indicam busca geral, não artista
    _COMMON_WORDS = {'top', 'best', 'hits', 'mix', 'remix', 'playlist', 'music', 'música',
                     'songs', 'músicas', 'ao vivo', 'live', 'cover', 'edit', 'version',
                     'oficial', 'official', 'video', 'clip', 'lyric', 'letra'}
    
    # Lista de canais/artistas conhecidos para auxiliar na detecção
    _KNOWN_ARTISTS = {
        'panda', 'vitor hugo', 'tubaroes', 'vitor hugo e tubaroes',
        'henrique e juliano', 'jorge e mateus', 'zé neto e cristiano',
        'marilia mendonça', 'gusttavo lima', 'luan santana',
        'anitta', 'ludmilla', 'ivete sangalo', 'caetano veloso',
        'gilberto gil', 'seu jorge', 'djavan', 'milton nascimento',
        'elton john', 'the beatles', 'queen', 'michael jackson',
        'adele', 'ed sheeran', 'bts', 'coldplay', 'imagine dragons',
        'mc hariel', 'mc livinho', 'mc kevin', 'mc don Juan',
        'mc ig', 'mc paiva', 'mc marcinho', 'mc bob rum',
    }
    
    def __init__(self, download_dir: str = "./downloads"):
        """
        Inicializa o serviço com diretório de downloads.
        
        Args:
            download_dir: Diretório onde os arquivos serão salvos
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
    
    def _detect_search_type(self, query: str) -> str:
        """
        Detecta inteligentemente o tipo de busca:
        - 'artist': quando o termo parece ser nome de artista/banda
        - 'music': quando parece ser nome de música específica
        - 'playlist': quando parece ser busca por playlist
        - 'general': quando não se encaixa nos acima
        
        Baseado no comportamento do SanpTune.
        """
        query_lower = query.lower().strip()
        
        # Se contém palavras comuns de playlist, é busca de playlist
        playlist_keywords = ['playlist', 'setlist', 'set list', 'podcast', 'album completo',
                            'full album', 'disco completo', 'discografia', 'discography',
                            'collection', 'coletânea', 'coletanea']
        if any(kw in query_lower for kw in playlist_keywords):
            return 'playlist'
        
        # Se é explicitamente um nome de artista conhecido, busca só dele
        if query_lower in self._KNOWN_ARTISTS:
            return 'artist'
        
        # Verifica se o termo contém nome de artista conhecido
        for artist in self._KNOWN_ARTISTS:
            if artist in query_lower:
                return 'artist'
        
        # Se contém " - " geralmente é "Artista - Música"
        if ' - ' in query:
            return 'music'
        
        # Se o termo tem 1-3 palavras e não contém palavras comuns, provável artista
        words = query_lower.split()
        if 1 <= len(words) <= 3:
            has_common = any(w in self._COMMON_WORDS for w in words)
            if not has_common:
                return 'artist'
        
        # Se contém palavras de ação musical, provável música específica
        music_actions = ['ouvir', 'ouça', 'escutar', 'tocar', 'play', 'reproduzir',
                        'musica', 'música', 'song', 'track', 'single']
        if any(ma in query_lower for ma in music_actions):
            return 'music'
        
        return 'general'
    
    def _build_intelligent_query(self, query: str, search_type: str) -> str:
        """
        Constrói uma query de busca inteligente baseada no tipo detectado.
        SanpTune-style: otimiza resultados para música, filtrando ruídos.
        """
        if search_type == 'artist':
            # Busca específica por artista - adiciona filtros de música
            # Remove palavras soltas que podem poluir
            cleaned = query
            # Busca apenas músicas oficiais do artista
            return f'"{cleaned}" música oficial'
        
        elif search_type == 'music':
            # Já é uma música específica, busca direta
            return query
        
        elif search_type == 'playlist':
            # Já é busca de playlist, mantém
            return query
        
        return query
    
    def _is_artist_or_band_query(self, query: str) -> bool:
        """
        Verifica se a query parece ser especificamente um artista/banda.
        Usado para filtrar resultados e mostrar apenas músicas desse artista.
        """
        query_lower = query.lower().strip()
        
        # Verifica lista de artistas conhecidos
        if query_lower in self._KNOWN_ARTISTS:
            return True
        
        # Verifica se alguma parte do nome corresponde a artista conhecido
        for artist in self._KNOWN_ARTISTS:
            if len(artist.split()) >= 2 and artist in query_lower:
                return True
        
        return False
    
    def _filter_by_artist(self, entries: List[dict], artist_name: str) -> List[dict]:
        """
        Filtra os resultados para mostrar apenas músicas do artista especificado.
        Similar ao SanpTune quando você pesquisa um artista específico.
        """
        artist_lower = artist_name.lower().strip()
        filtered = []
        
        for entry in entries:
            if not entry:
                continue
            
            # Obtém informações do canal/artista
            channel = (entry.get('channel', '') or entry.get('uploader', '') or '').lower()
            title = (entry.get('title', '') or '').lower()
            
            # Verifica se o canal ou título contém o nome do artista
            # Isso filtra videos de outros canais que não são do artista
            is_match = (
                artist_lower in channel or
                artist_lower in title or
                self._artist_in_title(artist_lower, title) or
                self._artist_in_title(artist_lower, channel)
            )
            
            if is_match:
                filtered.append(entry)
        
        # Se não encontrou nada com filtro, retorna todos (fallback)
        if not filtered:
            return entries
            
        return filtered
    
    def _artist_in_title(self, artist_lower: str, title: str) -> bool:
        """Verifica se o nome do artista aparece como palavra completa no título."""
        parts = artist_lower.split()
        return all(part in title for part in parts)
    
    def _get_ydl_options_search(self, max_results: int = 10) -> dict:
        """
        Configurações do yt-dlp para busca.
        Agora busca com mais profundidade para melhorar resultados.
        """
        return {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlistend': max_results * 3,
            'noplaylist': False,
            'match_filter': None,
        }
    
    def _get_ydl_options_playlist(self, max_results: int = 50) -> dict:
        """Configurações para extrair playlist."""
        return {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'playlistend': max_results,
            'noplaylist': False,
        }
    
    async def search_videos(self, query: str, max_results: int = 10,
                           mode: str = 'listen', include_playlists: bool = True,
                           type_filter: str = 'auto') -> Tuple[List[VideoMetadata], List[PlaylistMetadata], str]:
        """
        Busca vídeos no YouTube de forma ASSÍNCRONA com busca inteligente.
        
        Args:
            query: Termo de busca
            max_results: Número máximo de resultados
            mode: 'listen' para URL de stream, 'download' para URL de download direto
            include_playlists: Se deve incluir playlists na busca
            type_filter: 'auto', 'video', 'playlist', 'music', 'artist'
            
        Returns:
            Tupla (lista_videos, lista_playlists, tipo_busca_detectado)
        """
        search_type = type_filter if type_filter != 'auto' else self._detect_search_type(query)
        intelligent_query = self._build_intelligent_query(query, search_type)
        
        loop = asyncio.get_event_loop()
        
        def _search():
            try:
                ydl_opts = self._get_ydl_options_search(max_results)
                videos = []
                playlists = []
                
                # Se a query for uma URL direta, extrai metadados
                if query.startswith(('http://', 'https://')):
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(query, download=False)
                        if info:
                            if 'entries' in info:  # Playlist
                                entries = info['entries'][:max_results]
                                pl_meta = PlaylistMetadata(
                                    playlist_id=info.get('id', ''),
                                    title=info.get('title', 'Playlist'),
                                    thumbnail=info.get('thumbnail', ''),
                                    channel=info.get('channel', info.get('uploader')),
                                    video_count=len(entries),
                                    url=f"https://www.youtube.com/playlist?list={info.get('id', '')}"
                                )
                                playlists.append(pl_meta)
                                videos = self._parse_video_info(entries)
                            else:  # Vídeo único
                                videos = self._parse_video_info([info])
                else:
                    # Busca inteligente por termo
                    search_url = f'ytsearch{max_results * 2}:{intelligent_query}'
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(search_url, download=False)
                        if info and 'entries' in info:
                            entries = list(info['entries'])
                            
                            if search_type == 'artist' and self._is_artist_or_band_query(query):
                                entries = self._filter_by_artist(entries, query)
                            
                            # Separa playlists de vídeos
                            video_entries = []
                            for entry in entries:
                                if not entry:
                                    continue
                                ie_key = entry.get('ie_key', '') or ''
                                is_playlist = (
                                    entry.get('_type', '') == 'playlist' or
                                    'playlist' in ie_key.lower() or
                                    entry.get('playlist_id')
                                )
                                if is_playlist and include_playlists:
                                    pl = PlaylistMetadata(
                                        playlist_id=entry.get('id', entry.get('playlist_id', '')),
                                        title=entry.get('title', 'Playlist'),
                                        thumbnail=entry.get('thumbnail', ''),
                                        channel=entry.get('channel', entry.get('uploader')),
                                        video_count=entry.get('playlist_count', entry.get('n_entries', 0)),
                                        url=entry.get('webpage_url', '')
                                    )
                                    if pl.playlist_id and pl.playlist_id not in [p.playlist_id for p in playlists]:
                                        playlists.append(pl)
                                else:
                                    video_entries.append(entry)
                            
                            videos = self._parse_video_info(video_entries[:max_results])
                    
                    # Busca extra por playlists
                    if include_playlists and search_type != 'music':
                        try:
                            playlist_search_url = f'ytsearch{max_results}:{query} playlist'
                            with yt_dlp.YoutubeDL(self._get_ydl_options_search(max_results)) as ydl:
                                pl_info = ydl.extract_info(playlist_search_url, download=False)
                                if pl_info and 'entries' in pl_info:
                                    for entry in pl_info['entries']:
                                        if not entry:
                                            continue
                                        ie_key = entry.get('ie_key', '') or ''
                                        if 'playlist' in ie_key.lower() or entry.get('_type') == 'playlist':
                                            pl = PlaylistMetadata(
                                                playlist_id=entry.get('id', ''),
                                                title=entry.get('title', 'Playlist'),
                                                thumbnail=entry.get('thumbnail', ''),
                                                channel=entry.get('channel', entry.get('uploader')),
                                                video_count=entry.get('playlist_count', 0),
                                                url=entry.get('webpage_url', '')
                                            )
                                            if pl.playlist_id and pl.playlist_id not in [p.playlist_id for p in playlists]:
                                                playlists.append(pl)
                        except Exception:
                            pass
                
                # Anexa URLs de acordo com o modo
                if mode == 'download' and videos:
                    videos = self._attach_download_urls(videos)
                elif mode == 'listen' and videos:
                    videos = self._attach_stream_urls(videos)
                
                return videos, playlists, search_type
                
            except Exception as e:
                raise Exception(f"Erro ao buscar vídeos: {str(e)}")
        
        return await loop.run_in_executor(None, _search)
    
    def _attach_stream_urls(self, videos: List[VideoMetadata]) -> List[VideoMetadata]:
        """
        Anexa URL de stream de áudio para ouvir online (modo listen).
        """
        import requests as sync_requests
        
        def _get_stream(video_id: str) -> Optional[str]:
            try:
                api_url = "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
                payload = {
                    "context": {
                        "client": {
                            "clientName": "ANDROID",
                            "clientVersion": "19.09.37",
                            "androidSdkVersion": 34,
                        }
                    },
                    "videoId": video_id,
                }
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36',
                    'Content-Type': 'application/json',
                }
                resp = sync_requests.post(api_url, json=payload, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    streaming_data = data.get('streamingData', {})
                    for fmt in streaming_data.get('adaptiveFormats', []):
                        mime = fmt.get('mimeType', '')
                        if mime.startswith('audio/'):
                            url = fmt.get('url', '')
                            if url:
                                return url
            except Exception:
                pass
            
            # Fallback: yt-dlp
            try:
                url = f"https://www.youtube.com/watch?v={video_id}"
                opts = {
                    'quiet': True, 'no_warnings': True, 'download': False,
                    'format': 'bestaudio/best',
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        formats = info.get('formats', [])
                        audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('url')]
                        if audio_formats:
                            audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                            return audio_formats[0].get('url')
            except Exception:
                pass
            
            return None
        
        for video in videos:
            if video.video_id:
                stream = _get_stream(video.video_id)
                if stream:
                    video.stream_url = stream
        
        return videos
    
    def _attach_download_urls(self, videos: List[VideoMetadata]) -> List[VideoMetadata]:
        """
        Anexa URL de download direto do áudio original (modo download).
        Diferente do stream, aqui tenta pegar o formato de áudio mais próximo do original.
        """
        import requests as sync_requests
        
        def _get_download_url(video_id: str) -> Optional[Tuple[str, str]]:
            try:
                api_url = "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
                payload = {
                    "context": {
                        "client": {
                            "clientName": "ANDROID",
                            "clientVersion": "19.09.37",
                            "androidSdkVersion": 34,
                        }
                    },
                    "videoId": video_id,
                }
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36',
                    'Content-Type': 'application/json',
                }
                resp = sync_requests.post(api_url, json=payload, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    streaming_data = data.get('streamingData', {})
                    audio_formats = []
                    for fmt in streaming_data.get('adaptiveFormats', []):
                        mime = fmt.get('mimeType', '')
                        if mime.startswith('audio/'):
                            url = fmt.get('url', '')
                            if url:
                                audio_formats.append({
                                    'url': url,
                                    'abr': fmt.get('bitrate', 0),
                                    'mime': mime,
                                    'ext': mime.split('/')[-1].split(';')[0],
                                })
                    
                    if audio_formats:
                        audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                        best = audio_formats[0]
                        return best['url'], best['ext']
            except Exception:
                pass
            
            # Fallback: yt-dlp
            try:
                url = f"https://www.youtube.com/watch?v={video_id}"
                opts = {
                    'quiet': True, 'no_warnings': True, 'download': False,
                    'format': 'bestaudio/best',
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        formats = info.get('formats', [])
                        audio = [f for f in formats if f.get('acodec') != 'none' and f.get('url')]
                        if audio:
                            audio.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                            best = audio[0]
                            url = best.get('url', '')
                            ext = best.get('ext', 'webm')
                            if url:
                                return url, ext
            except Exception:
                pass
            
            return None, None
        
        for video in videos:
            if video.video_id:
                dl_url, _ = _get_download_url(video.video_id)
                if dl_url:
                    video.stream_url = dl_url
        
        return videos
    
    def _parse_video_info(self, entries: List[dict]) -> List[VideoMetadata]:
        """
        Converte informações brutas do yt-dlp para VideoMetadata.
        """
        videos = []
        for entry in entries:
            if not entry:
                continue
            
            # Pula entradas de playlist
            if entry.get('_type') == 'playlist' or ('ie_key' in entry and 'playlist' in str(entry.get('ie_key', '')).lower()):
                continue
            
            video = VideoMetadata(
                video_id=entry.get('id', ''),
                title=entry.get('title', 'Sem título'),
                thumbnail=entry.get('thumbnail', ''),
                duration=entry.get('duration', 0),
                url=f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                channel=entry.get('channel', entry.get('uploader')),
                view_count=entry.get('view_count'),
                upload_date=entry.get('upload_date'),
                result_type='video',
                stream_url=None,
            )
            videos.append(video)
        
        return videos
    
    async def get_playlist_items(self, playlist_id: str, max_results: int = 50) -> Tuple[str, str, Optional[str], int, List[VideoMetadata]]:
        """
        Extrai todos os vídeos de uma playlist.
        
        Returns:
            Tupla (titulo_playlist, url_playlist, canal, total_videos, lista_videos)
        """
        loop = asyncio.get_event_loop()
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
        
        def _extract():
            try:
                opts = self._get_ydl_options_playlist(max_results)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(playlist_url, download=False)
                    
                    if not info:
                        raise Exception("Playlist não encontrada")
                    
                    playlist_title = info.get('title', 'Playlist')
                    channel = info.get('channel', info.get('uploader'))
                    
                    entries = info.get('entries', [])
                    if not entries:
                        entries = []
                    
                    videos = self._parse_video_info(entries)
                    total = len(entries)
                    
                    return playlist_title, playlist_url, channel, total, videos
                    
            except Exception as e:
                raise Exception(f"Erro ao extrair playlist: {str(e)}")
        
        return await loop.run_in_executor(None, _extract)
    
    async def get_audio_stream_url(self, video_id: str) -> dict:
        """
        Extrai a URL de stream de áudio crua do YouTube.
        Usa requests para acessar diretamente o endpoint de video info do YouTube
        (mesma abordagem do pytube), sem depender de yt-dlp.
        Não baixa nada no servidor, apenas retorna a URL direta do áudio (m4a, webm, etc.).
        """
        import requests as sync_requests
        loop = asyncio.get_event_loop()
        
        def _fetch_direct():
            """Acessa diretamente o YouTube via API interna (endpoint do app Android)"""
            headers = {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36',
                'Content-Type': 'application/json',
            }
            
            api_url = "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
            
            payload = {
                "context": {
                    "client": {
                        "clientName": "ANDROID",
                        "clientVersion": "19.09.37",
                        "androidSdkVersion": 34,
                    }
                },
                "videoId": video_id,
            }
            
            resp = sync_requests.post(api_url, json=payload, headers=headers, timeout=15)
            
            if resp.status_code != 200:
                raise Exception(f"Falha ao acessar API YouTube: HTTP {resp.status_code}")
            
            data = resp.json()
            
            video_details = data.get('videoDetails', {})
            title = video_details.get('title', '')
            duration = int(video_details.get('lengthSeconds', 0))
            thumbnail = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'
            
            streaming_data = data.get('streamingData', {})
            audio_urls = []
            
            for fmt in streaming_data.get('adaptiveFormats', []):
                mime = fmt.get('mimeType', '')
                if mime.startswith('audio/'):
                    url = fmt.get('url', '')
                    if url:
                        audio_urls.append({
                            'url': url,
                            'abr': fmt.get('bitrate', 0),
                            'mime': mime,
                            'ext': mime.split('/')[-1].split(';')[0],
                        })
            
            if not audio_urls:
                for fmt in streaming_data.get('adaptiveFormats', []):
                    mime = fmt.get('mimeType', '')
                    if mime.startswith('audio/'):
                        cipher = fmt.get('signatureCipher', '')
                        if cipher:
                            import urllib.parse
                            parsed = urllib.parse.parse_qs(cipher)
                            url = parsed.get('url', [''])[0]
                            audio_urls.append({
                                'url': url,
                                'abr': fmt.get('bitrate', 0),
                                'mime': mime,
                                'ext': mime.split('/')[-1].split(';')[0],
                            })
            
            if not audio_urls:
                raise Exception("Nenhum formato de áudio encontrado")
            
            best = max(audio_urls, key=lambda x: x.get('abr', 0) or 0)
            
            return {
                'stream_url': best['url'],
                'duration': duration,
                'title': title,
                'thumbnail': thumbnail,
                'format': '',
                'ext': best['ext'],
            }
        
        def _fetch_from_ytdlp():
            """Fallback: tenta yt-dlp"""
            try:
                url = f"https://www.youtube.com/watch?v={video_id}"
                opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'extract_flat': False,
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        formats = info.get('formats', [])
                        audio = [f for f in formats if f.get('acodec') != 'none' and f.get('url')]
                        audio.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                        if audio:
                            best = audio[0]
                            return {
                                'stream_url': best.get('url'),
                                'duration': info.get('duration', 0),
                                'title': info.get('title', ''),
                                'thumbnail': info.get('thumbnail', ''),
                                'format': best.get('format', ''),
                                'ext': best.get('ext', ''),
                            }
            except Exception:
                pass
            return None
        
        def _fetch_from_piped():
            """Fallback: tenta Piped API"""
            piped_instances = [
                f"https://pipedapi.kavin.rocks/streams/{video_id}",
                f"https://pipedapi.r4fo.com/streams/{video_id}",
            ]
            for api_url in piped_instances:
                try:
                    resp = sync_requests.get(api_url, timeout=10, headers={
                        'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                    })
                    if resp.status_code == 200:
                        data = resp.json()
                        audio_streams = data.get('audioStreams', [])
                        if audio_streams:
                            best = max(audio_streams, key=lambda x: x.get('bitrate', 0) or 0)
                            return {
                                'stream_url': best.get('url'),
                                'duration': data.get('duration', 0),
                                'title': data.get('title', ''),
                                'thumbnail': data.get('thumbnailUrl', ''),
                                'format': best.get('quality', ''),
                                'ext': best.get('format', 'webm').split('/')[-1].split(';')[0],
                            }
                except Exception:
                    continue
            return None
        
        def _get_stream_url():
            errors = []
            
            # 1. Tenta extração direta
            try:
                return _fetch_direct()
            except Exception as e:
                errors.append(f"direct: {str(e)[:100]}")
            
            # 2. Tenta yt-dlp
            try:
                result = _fetch_from_ytdlp()
                if result:
                    return result
            except Exception as e:
                errors.append(f"ytdlp: {str(e)[:100]}")
            
            # 3. Tenta Piped
            try:
                result = _fetch_from_piped()
                if result:
                    return result
            except Exception as e:
                errors.append(f"piped: {str(e)[:100]}")
            
            raise Exception(f"Todas as fontes falharam: {' | '.join(errors)}")
        
        return await loop.run_in_executor(None, _get_stream_url)
    
    async def get_direct_download_url(self, video_id: str) -> dict:
        """
        Extrai a URL de download direto do áudio original (melhor qualidade).
        Diferente do stream URL que pode usar codecs de streaming,
        esta função prioriza formatos de áudio para download permanente.
        
        Returns:
            Dict com url, ext, title, duration, thumbnail
        """
        import requests as sync_requests
        loop = asyncio.get_event_loop()
        
        def _fetch():
            try:
                # Tenta primeiro via API Android para maior taxa de sucesso
                api_url = "https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
                payload = {
                    "context": {
                        "client": {
                            "clientName": "ANDROID",
                            "clientVersion": "19.09.37",
                            "androidSdkVersion": 34,
                        }
                    },
                    "videoId": video_id,
                }
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36',
                    'Content-Type': 'application/json',
                }
                resp = sync_requests.post(api_url, json=payload, headers=headers, timeout=15)
                
                if resp.status_code == 200:
                    data = resp.json()
                    video_details = data.get('videoDetails', {})
                    title = video_details.get('title', '')
                    duration = int(video_details.get('lengthSeconds', 0))
                    thumbnail = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'
                    
                    streaming_data = data.get('streamingData', {})
                    audio_formats = []
                    
                    for fmt in streaming_data.get('adaptiveFormats', []):
                        mime = fmt.get('mimeType', '')
                        if mime.startswith('audio/'):
                            url = fmt.get('url', '')
                            if url:
                                audio_formats.append({
                                    'url': url,
                                    'abr': fmt.get('bitrate', 0),
                                    'mime': mime,
                                    'ext': mime.split('/')[-1].split(';')[0],
                                })
                    
                    if audio_formats:
                        # Para download, prioriza melhor qualidade (maior bitrate)
                        audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                        best = audio_formats[0]
                        ext = best['ext']
                        if ext == 'mp4':
                            ext = 'm4a'
                        return {
                            'download_url': best['url'],
                            'ext': ext,
                            'title': title,
                            'duration': duration,
                            'thumbnail': thumbnail,
                        }
            except Exception:
                pass
            
            # Fallback via yt-dlp
            try:
                url = f"https://www.youtube.com/watch?v={video_id}"
                opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'format': 'bestaudio/best',
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        formats = info.get('formats', [])
                        audio = [f for f in formats if f.get('acodec') != 'none' and f.get('url')]
                        if audio:
                            audio.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                            best = audio[0]
                            ext = best.get('ext', 'webm')
                            return {
                                'download_url': best.get('url'),
                                'ext': ext,
                                'title': info.get('title', ''),
                                'duration': info.get('duration', 0),
                                'thumbnail': info.get('thumbnail', ''),
                            }
            except Exception:
                pass
            
            raise Exception("Não foi possível obter URL de download")
        
        return await loop.run_in_executor(None, _fetch)
    
    def processar_midia(
        self, 
        caminho_entrada: str, 
        caminho_saida: str, 
        **kwargs
    ) -> bool:
        """
        Processa mídia usando FFmpeg via subprocess com tratamento de erros robusto.
        """
        try:
            print(f"[FFmpeg] Processando: {caminho_entrada} -> {caminho_saida}")
            
            cmd = ['ffmpeg', '-i', caminho_entrada]
            
            for key, value in kwargs.items():
                if key == 'acodec':
                    cmd.extend(['-acodec', str(value)])
                elif key == 'ab':
                    cmd.extend(['-ab', str(value)])
                elif key == 'vn' and value is None:
                    cmd.append('-vn')
                elif key == 'ar':
                    cmd.extend(['-ar', str(value)])
                elif key == 'ac':
                    cmd.extend(['-ac', str(value)])
                elif key == 'f':
                    cmd.extend(['-f', str(value)])
                else:
                    cmd.extend([f'-{key}', str(value)])
            
            cmd.extend(['-y', caminho_saida])
            
            print(f"[FFmpeg] Comando: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode != 0:
                print(f"[FFmpeg] Erro no processamento: {result.stderr}")
                return False
            
            if os.path.exists(caminho_saida):
                print(f"[FFmpeg] Processamento concluído com sucesso: {caminho_saida}")
                if os.path.exists(caminho_entrada):
                    os.remove(caminho_entrada)
                    print(f"[FFmpeg] Arquivo original deletado: {caminho_entrada}")
                return True
            else:
                print(f"[FFmpeg] Erro: Arquivo de saída não foi criado")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"[FFmpeg] Erro: Timeout no processamento")
            return False
        except FileNotFoundError:
            print(f"[FFmpeg] Erro: FFmpeg não encontrado no sistema. Instale ffmpeg ou use Docker.")
            return False
        except Exception as e:
            print(f"[FFmpeg] Erro inesperado: {str(e)}")
            return False
    
    async def download_audio(self, video_id: str, output_format: str = 'original') -> tuple:
        """
        Baixa áudio do YouTube e opcionalmente converte usando FFmpeg.
        
        Args:
            video_id: ID do vídeo
            output_format: 'original' (sem conversão), 'mp3', 'm4a', etc.
            
        Returns:
            Tupla com (caminho do arquivo, tamanho em bytes, duração)
        """
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        def _download():
            try:
                if output_format == 'original':
                    # Baixa no formato original sem conversão
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'quiet': True,
                        'no_warnings': True,
                        'outtmpl': str(self.download_dir / f'{video_id}.%(ext)s'),
                    }
                else:
                    # Baixa e converte
                    ydl_opts = {
                        'format': 'bestaudio',
                        'quiet': True,
                        'no_warnings': True,
                        'outtmpl': str(self.download_dir / f'{video_id}.%(ext)s'),
                    }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    
                    if not info:
                        raise Exception("Não foi possível baixar o vídeo")
                    
                    downloaded_file = None
                    downloaded_ext = None
                    for ext in ['m4a', 'webm', 'mp4', 'opus', 'ogg']:
                        test_file = self.download_dir / f"{video_id}.{ext}"
                        if test_file.exists():
                            downloaded_file = str(test_file)
                            downloaded_ext = ext
                            break
                    
                    if not downloaded_file:
                        raise Exception("Arquivo baixado não encontrado")
                    
                    if output_format == 'original':
                        # Retorna o arquivo no formato original
                        file_size = os.path.getsize(downloaded_file)
                        duration = info.get('duration', 0)
                        return downloaded_file, file_size, duration, downloaded_ext
                    
                    # Converte para o formato solicitado
                    output_file = str(self.download_dir / f"{video_id}.{output_format}")
                    
                    ffmpeg_args = {
                        'acodec': 'libmp3lame' if output_format == 'mp3' else 'aac',
                        'ab': '192k',
                        'vn': None,
                    }
                    
                    success = self.processar_midia(downloaded_file, output_file, **ffmpeg_args)
                    
                    if not success:
                        raise Exception("Falha na conversão FFmpeg")
                    
                    file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
                    duration = info.get('duration', 0)
                    
                    return output_file, file_size, duration, output_format
                    
            except Exception as e:
                raise Exception(f"Erro ao baixar/converter áudio: {str(e)}")
        
        return await loop.run_in_executor(None, _download)
    
    async def download_batch(self, video_ids: List[str], output_format: str = 'original') -> List[dict]:
        """
        Baixa múltiplos vídeos em lote (para playlists).
        
        Args:
            video_ids: Lista de IDs de vídeo
            output_format: Formato de saída
            
        Returns:
            Lista de resultados de download
        """
        results = []
        for video_id in video_ids:
            try:
                filepath, file_size, duration, ext = await self.download_audio(
                    video_id=video_id,
                    output_format=output_format
                )
                results.append({
                    'video_id': video_id,
                    'success': True,
                    'filepath': filepath,
                    'file_size': file_size,
                    'duration': duration,
                    'ext': ext,
                })
            except Exception as e:
                results.append({
                    'video_id': video_id,
                    'success': False,
                    'error': str(e),
                })
        return results