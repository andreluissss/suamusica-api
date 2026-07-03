"""
Servico para integracao com yt-dlp.
Responsavel por buscar metadados e baixar audio do YouTube.
Implementa busca inteligente com deteccao de artistas, musicas e playlists.
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
import time


class YouTubeService:
    """Servico para interacao com YouTube usando yt-dlp."""

    _COMMON_WORDS = {'top', 'best', 'hits', 'mix', 'remix', 'playlist', 'music', 'musica',
                     'songs', 'musicas', 'ao vivo', 'live', 'cover', 'edit', 'version',
                     'oficial', 'official', 'video', 'clip', 'lyric', 'letra'}

    _KNOWN_ARTISTS = {
        'panda', 'vitor hugo', 'tubaroes', 'vitor hugo e tubaroes',
        'henrique e juliano', 'jorge e mateus', 'ze neto e cristiano',
        'marilia mendonca', 'gusttavo lima', 'luan santana',
        'anitta', 'ludmilla', 'ivete sangalo', 'caetano veloso',
        'gilberto gil', 'seu jorge', 'djavan', 'milton nascimento',
        'elton john', 'the beatles', 'queen', 'michael jackson',
        'adele', 'ed sheeran', 'bts', 'coldplay', 'imagine dragons',
        'mc hariel', 'mc livinho', 'mc kevin', 'mc don Juan',
        'mc ig', 'mc paiva', 'mc marcinho', 'mc bob rum',
    }

    def __init__(self, download_dir: str = "./downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _detect_search_type(self, query: str) -> str:
        query_lower = query.lower().strip()
        playlist_keywords = ['playlist', 'setlist', 'set list', 'podcast', 'album completo',
                            'full album', 'disco completo', 'discografia', 'discography',
                            'collection', 'coletanea', 'coletanea']
        if any(kw in query_lower for kw in playlist_keywords):
            return 'playlist'
        if query_lower in self._KNOWN_ARTISTS:
            return 'artist'
        for artist in self._KNOWN_ARTISTS:
            if artist in query_lower:
                return 'artist'
        if ' - ' in query:
            return 'music'
        words = query_lower.split()
        if 1 <= len(words) <= 3:
            has_common = any(w in self._COMMON_WORDS for w in words)
            if not has_common:
                return 'artist'
        music_actions = ['ouvir', 'ouca', 'escutar', 'tocar', 'play', 'reproduzir',
                        'musica', 'musica', 'song', 'track', 'single']
        if any(ma in query_lower for ma in music_actions):
            return 'music'
        return 'general'

    def _build_intelligent_query(self, query: str, search_type: str) -> str:
        if search_type == 'artist':
            return f'"{query}" musica oficial'
        return query

    def _is_artist_or_band_query(self, query: str) -> bool:
        query_lower = query.lower().strip()
        if query_lower in self._KNOWN_ARTISTS:
            return True
        for artist in self._KNOWN_ARTISTS:
            if len(artist.split()) >= 2 and artist in query_lower:
                return True
        return False

    def _filter_by_artist(self, entries: List[dict], artist_name: str) -> List[dict]:
        artist_lower = artist_name.lower().strip()
        filtered = []
        for entry in entries:
            if not entry:
                continue
            channel = (entry.get('channel', '') or entry.get('uploader', '') or '').lower()
            title = (entry.get('title', '') or '').lower()
            is_match = (
                artist_lower in channel or
                artist_lower in title or
                self._artist_in_title(artist_lower, title) or
                self._artist_in_title(artist_lower, channel)
            )
            if is_match:
                filtered.append(entry)
        if not filtered:
            return entries
        return filtered

    def _artist_in_title(self, artist_lower: str, title: str) -> bool:
        parts = artist_lower.split()
        return all(part in title for part in parts)

    def _get_ydl_options_search(self, max_results: int = 10) -> dict:
        return {
            'quiet': True, 'no_warnings': True, 'extract_flat': True,
            'playlistend': max_results * 3, 'noplaylist': False, 'match_filter': None,
        }

    def _get_ydl_options_playlist(self, max_results: int = 50) -> dict:
        return {
            'quiet': True, 'no_warnings': True, 'extract_flat': 'in_playlist',
            'playlistend': max_results, 'noplaylist': False,
        }

    def _get_yt_player_url(self, video_id: str) -> Optional[str]:
        """
        Obtem URL de audio diretamente da API Android do YouTube (youtubei/v1/player).
        Esta e a estrategia MAIS CONFIABLEL em servidores cloud, pois nao depende de scraping.
        Tenta multiplos clientes Android, Web e iOS para contornar bloqueios.
        """
        import requests as sync_requests
        import urllib.parse
        
        api_keys = [
            "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
            "AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w",
        ]
        client_configs = [
            {"clientName": "ANDROID", "clientVersion": "19.09.37", "androidSdkVersion": 34},
            {"clientName": "ANDROID_EMBEDDED_PLAYER", "clientVersion": "19.09.37", "androidSdkVersion": 34},
            {"clientName": "ANDROID_MUSIC", "clientVersion": "6.42.52", "androidSdkVersion": 34},
            {"clientName": "WEB", "clientVersion": "2.20240701.00.00"},
            {"clientName": "WEB_EMBEDDED_PLAYER", "clientVersion": "2.20240701.00.00"},
            {"clientName": "IOS", "clientVersion": "19.29.1", "deviceModel": "iPhone16,2"},
        ]
        
        headers = {
            'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)',
            'Content-Type': 'application/json',
            'x-youtube-client-name': '5',
            'x-youtube-client-version': '19.29.1',
        }
        
        for api_key in api_keys:
            for client in client_configs:
                try:
                    api_url = f"https://www.youtube.com/youtubei/v1/player?key={api_key}"
                    payload = {
                        "context": {
                            "client": client,
                            "thirdParty": {"embedUrl": "https://www.youtube.com"}
                        },
                        "videoId": video_id,
                        "playbackContext": {
                            "contentPlaybackContext": {
                                "html5Preference": "HTML5_PREF_WANTS",
                                "signatureTimestamp": 19400,
                            }
                        },
                        "racyCheckOk": True,
                        "contentCheckOk": True,
                    }
                    resp = sync_requests.post(api_url, json=payload, headers=headers, timeout=10)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        
                        # Verifica se ha streamingData
                        streaming_data = data.get('streamingData', {})
                        if not streaming_data:
                            continue
                        
                        # Procura formatos de audio
                        audio_urls = []
                        for fmt in streaming_data.get('adaptiveFormats', []):
                            mime = fmt.get('mimeType', '')
                            if mime.startswith('audio/'):
                                url = fmt.get('url', '')
                                if url:
                                    audio_urls.append({
                                        'url': url,
                                        'abr': fmt.get('bitrate', 0),
                                        'ext': mime.split('/')[-1].split(';')[0],
                                    })
                        
                        # Se nao achou URLs diretas, tenta decodificar cipher
                        if not audio_urls:
                            for fmt in streaming_data.get('adaptiveFormats', []):
                                mime = fmt.get('mimeType', '')
                                if mime.startswith('audio/'):
                                    cipher = fmt.get('signatureCipher', '') or fmt.get('cipher', '')
                                    if cipher:
                                        parsed = urllib.parse.parse_qs(cipher)
                                        url = parsed.get('url', [''])[0]
                                        if url:
                                            audio_urls.append({
                                                'url': url,
                                                'abr': fmt.get('bitrate', 0),
                                                'ext': mime.split('/')[-1].split(';')[0],
                                            })
                        
                        if audio_urls:
                            audio_urls.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                            return audio_urls[0]['url']
                            
                except Exception:
                    continue
        
        return None

    async def search_videos(self, query: str, max_results: int = 10,
                           mode: str = 'listen', include_playlists: bool = True,
                           type_filter: str = 'auto') -> Tuple[List[VideoMetadata], List[PlaylistMetadata], str]:
        search_type = type_filter if type_filter != 'auto' else self._detect_search_type(query)
        intelligent_query = self._build_intelligent_query(query, search_type)
        loop = asyncio.get_event_loop()

        def _search():
            try:
                ydl_opts = self._get_ydl_options_search(max_results)
                videos = []
                playlists = []

                if query.startswith(('http://', 'https://')):
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(query, download=False)
                        if info:
                            if 'entries' in info:
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
                            else:
                                videos = self._parse_video_info([info])
                else:
                    search_url = f'ytsearch{max_results * 2}:{intelligent_query}'
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(search_url, download=False)
                        if info and 'entries' in info:
                            entries = list(info['entries'])
                            if search_type == 'artist' and self._is_artist_or_band_query(query):
                                entries = self._filter_by_artist(entries, query)
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

                # Anexa URLs de stream/download usando a API Android (mais confiavel)
                if mode == 'download' and videos:
                    try:
                        videos = self._attach_download_urls(videos)
                    except Exception:
                        pass
                elif mode == 'listen' and videos:
                    try:
                        videos = self._attach_stream_urls(videos)
                    except Exception:
                        pass

                return videos, playlists, search_type
            except Exception as e:
                raise Exception(f"Erro ao buscar videos: {str(e)}")

        return await loop.run_in_executor(None, _search)

    def _attach_stream_urls(self, videos: List[VideoMetadata]) -> List[VideoMetadata]:
        for video in videos:
            if video.video_id:
                try:
                    url = self._get_yt_player_url(video.video_id)
                    if url:
                        video.stream_url = url
                except Exception:
                    pass
        return videos

    def _attach_download_urls(self, videos: List[VideoMetadata]) -> List[VideoMetadata]:
        for video in videos:
            if video.video_id:
                try:
                    url = self._get_yt_player_url(video.video_id)
                    if url:
                        video.stream_url = url
                except Exception:
                    pass
        return videos

    def _parse_video_info(self, entries: List[dict]) -> List[VideoMetadata]:
        videos = []
        for entry in entries:
            if not entry:
                continue
            if entry.get('_type') == 'playlist' or ('ie_key' in entry and 'playlist' in str(entry.get('ie_key', '')).lower()):
                continue
            video = VideoMetadata(
                video_id=entry.get('id', ''),
                title=entry.get('title', 'Sem titulo'),
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
        loop = asyncio.get_event_loop()
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

        def _extract():
            try:
                opts = self._get_ydl_options_playlist(max_results)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(playlist_url, download=False)
                    if not info:
                        raise Exception("Playlist nao encontrada")
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
        Obtem URL de stream de audio.
        Estrategia 1: YouTube Android API (mais confiavel em cloud)
        Estrategia 2: yt-dlp com anti-bloqueio (fallback)
        Estrategia 3: Piped API (ultimo recurso)
        """
        import requests as sync_requests
        import urllib.parse
        loop = asyncio.get_event_loop()

        def _fetch_via_api() -> Optional[dict]:
            """Estrategia PRINCIPAL: YouTube API Android."""
            api_keys = [
                "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
                "AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w",
            ]
            client_configs = [
                {"clientName": "ANDROID", "clientVersion": "19.09.37", "androidSdkVersion": 34},
                {"clientName": "ANDROID_EMBEDDED_PLAYER", "clientVersion": "19.09.37", "androidSdkVersion": 34},
                {"clientName": "ANDROID_MUSIC", "clientVersion": "6.42.52", "androidSdkVersion": 34},
                {"clientName": "WEB", "clientVersion": "2.20240701.00.00"},
                {"clientName": "IOS", "clientVersion": "19.29.1", "deviceModel": "iPhone16,2"},
            ]
            headers = {
                'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)',
                'Content-Type': 'application/json',
                'x-youtube-client-name': '5',
                'x-youtube-client-version': '19.29.1',
            }
            
            for api_key in api_keys:
                for client in client_configs:
                    try:
                        api_url = f"https://www.youtube.com/youtubei/v1/player?key={api_key}"
                        payload = {
                            "context": {"client": client},
                            "videoId": video_id,
                            "playbackContext": {
                                "contentPlaybackContext": {
                                    "html5Preference": "HTML5_PREF_WANTS",
                                    "signatureTimestamp": 19400,
                                }
                            },
                            "racyCheckOk": True,
                            "contentCheckOk": True,
                        }
                        resp = sync_requests.post(api_url, json=payload, headers=headers, timeout=10)
                        if resp.status_code == 200:
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
                                        cipher = fmt.get('signatureCipher', '') or fmt.get('cipher', '')
                                        if cipher:
                                            parsed = urllib.parse.parse_qs(cipher)
                                            url = parsed.get('url', [''])[0]
                                            if url:
                                                audio_urls.append({
                                                    'url': url,
                                                    'abr': fmt.get('bitrate', 0),
                                                    'mime': mime,
                                                    'ext': mime.split('/')[-1].split(';')[0],
                                                })
                            
                            if audio_urls:
                                best = max(audio_urls, key=lambda x: x.get('abr', 0) or 0)
                                return {
                                    'stream_url': best['url'],
                                    'duration': duration,
                                    'title': title,
                                    'thumbnail': thumbnail,
                                    'format': '',
                                    'ext': best['ext'],
                                }
                    except Exception:
                        continue
            return None

        def _fetch_via_ytdlp() -> Optional[dict]:
            """Estrategia 2: yt-dlp fallback."""
            try:
                url = f"https://www.youtube.com/watch?v={video_id}"
                opts = {
                    'quiet': True, 'no_warnings': True, 'download': False,
                    'extract_flat': False, 'format': 'bestaudio/best',
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36',
                    },
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        formats = info.get('formats', [])
                        audio = [f for f in formats if f.get('acodec') != 'none' and f.get('url')]
                        if audio:
                            audio.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                            best = audio[0]
                            return {
                                'stream_url': best.get('url'),
                                'duration': info.get('duration', 0),
                                'title': info.get('title', ''),
                                'thumbnail': info.get('thumbnail', ''),
                                'format': best.get('format', ''),
                                'ext': best.get('ext', ''),
                            }
            except Exception as e:
                print(f"[ytdlp] Erro: {str(e)[:100]}")
            return None

        def _fetch_via_piped() -> Optional[dict]:
            """Estrategia 3: Piped API."""
            piped_instances = ["https://pipedapi.kavin.rocks", "https://pipedapi.r4fo.com"]
            for instance in piped_instances:
                try:
                    api_url = f"{instance}/streams/{video_id}"
                    resp = sync_requests.get(api_url, timeout=10, headers={
                        'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                    })
                    if resp.status_code == 200:
                        data = resp.json()
                        audio_streams = data.get('audioStreams', [])
                        if audio_streams:
                            best = max(audio_streams, key=lambda x: x.get('bitrate', 0) or 0)
                            ext = best.get('format', 'webm').split('/')[-1].split(';')[0]
                            return {
                                'stream_url': best.get('url'),
                                'duration': data.get('duration', 0),
                                'title': data.get('title', ''),
                                'thumbnail': data.get('thumbnailUrl', ''),
                                'format': best.get('quality', ''),
                                'ext': ext,
                            }
                except Exception:
                    continue
            return None

        def _get_stream_url():
            errors = []
            
            # 1. YouTube API (principal - mais confiavel em cloud)
            result = _fetch_via_api()
            if result and result.get('stream_url'):
                return result
            errors.append("api: sem stream URL")
            
            # 2. yt-dlp (fallback)
            result = _fetch_via_ytdlp()
            if result and result.get('stream_url'):
                return result
            errors.append("ytdlp: sem stream URL")
            
            # 3. Piped (ultimo recurso)
            result = _fetch_via_piped()
            if result and result.get('stream_url'):
                return result
            errors.append("piped: sem stream URL")
            
            return {
                'stream_url': None, 'duration': 0, 'title': '', 'format': '', 'ext': '',
                'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
                'error': ' | '.join(errors),
            }

        return await loop.run_in_executor(None, _get_stream_url)

    async def get_direct_download_url(self, video_id: str) -> dict:
        """
        Obtem URL de download direto do audio.
        Estrategia 1: YouTube Android API (mais confiavel em cloud)
        Estrategia 2: yt-dlp (fallback)
        """
        import urllib.parse
        loop = asyncio.get_event_loop()
        import requests as sync_requests

        def _fetch_via_api() -> Optional[dict]:
            """Estrategia PRINCIPAL: YouTube API Android."""
            api_keys = [
                "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
                "AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w",
            ]
            client_configs = [
                {"clientName": "ANDROID", "clientVersion": "19.09.37", "androidSdkVersion": 34},
                {"clientName": "ANDROID_EMBEDDED_PLAYER", "clientVersion": "19.09.37", "androidSdkVersion": 34},
                {"clientName": "ANDROID_MUSIC", "clientVersion": "6.42.52", "androidSdkVersion": 34},
                {"clientName": "WEB", "clientVersion": "2.20240701.00.00"},
                {"clientName": "IOS", "clientVersion": "19.29.1", "deviceModel": "iPhone16,2"},
            ]
            headers = {
                'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X)',
                'Content-Type': 'application/json',
                'x-youtube-client-name': '5',
                'x-youtube-client-version': '19.29.1',
            }
            
            for api_key in api_keys:
                for client in client_configs:
                    try:
                        api_url = f"https://www.youtube.com/youtubei/v1/player?key={api_key}"
                        payload = {
                            "context": {"client": client},
                            "videoId": video_id,
                            "playbackContext": {
                                "contentPlaybackContext": {
                                    "html5Preference": "HTML5_PREF_WANTS",
                                    "signatureTimestamp": 19400,
                                }
                            },
                            "racyCheckOk": True,
                            "contentCheckOk": True,
                        }
                        resp = sync_requests.post(api_url, json=payload, headers=headers, timeout=10)
                        if resp.status_code == 200:
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
                                        cipher = fmt.get('signatureCipher', '') or fmt.get('cipher', '')
                                        if cipher:
                                            parsed = urllib.parse.parse_qs(cipher)
                                            url = parsed.get('url', [''])[0]
                                            if url:
                                                audio_urls.append({
                                                    'url': url,
                                                    'abr': fmt.get('bitrate', 0),
                                                    'mime': mime,
                                                    'ext': mime.split('/')[-1].split(';')[0],
                                                })
                            
                            if audio_urls:
                                audio_urls.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                                best = audio_urls[0]
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
                        continue
            return None

        def _fetch_via_ytdlp() -> Optional[dict]:
            """Estrategia 2: yt-dlp fallback."""
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
                            ext = best.get('ext', 'webm')
                            if ext == 'mp4':
                                ext = 'm4a'
                            return {
                                'download_url': best.get('url'),
                                'ext': ext,
                                'title': info.get('title', ''),
                                'duration': info.get('duration', 0),
                                'thumbnail': info.get('thumbnail', ''),
                            }
            except Exception:
                pass
            return None

        def _fetch() -> dict:
            # 1. YouTube API (principal)
            result = _fetch_via_api()
            if result and result.get('download_url'):
                return result
            
            # 2. yt-dlp (fallback)
            result = _fetch_via_ytdlp()
            if result and result.get('download_url'):
                return result
            
            return {
                'download_url': None, 'ext': 'unknown', 'title': '',
                'duration': 0, 'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
            }

        return await loop.run_in_executor(None, _fetch)

    def processar_midia(self, caminho_entrada: str, caminho_saida: str, **kwargs) -> bool:
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                return False
            if os.path.exists(caminho_saida):
                if os.path.exists(caminho_entrada):
                    os.remove(caminho_entrada)
                return True
            return False
        except Exception as e:
            print(f"[FFmpeg] Erro: {str(e)}")
            return False

    async def download_audio(self, video_id: str, output_format: str = 'original') -> tuple:
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"

        def _download():
            try:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'quiet': True, 'no_warnings': True,
                    'outtmpl': str(self.download_dir / f'{video_id}.%(ext)s'),
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        raise Exception("Nao foi possivel baixar o video")
                    downloaded_file = None
                    downloaded_ext = None
                    for ext in ['m4a', 'webm', 'mp4', 'opus', 'ogg']:
                        test_file = self.download_dir / f"{video_id}.{ext}"
                        if test_file.exists():
                            downloaded_file = str(test_file)
                            downloaded_ext = ext
                            break
                    if not downloaded_file:
                        raise Exception("Arquivo baixado nao encontrado")
                    if output_format == 'original':
                        file_size = os.path.getsize(downloaded_file)
                        duration = info.get('duration', 0)
                        return downloaded_file, file_size, duration, downloaded_ext
                    output_file = str(self.download_dir / f"{video_id}.{output_format}")
                    ffmpeg_args = {
                        'acodec': 'libmp3lame' if output_format == 'mp3' else 'aac',
                        'ab': '192k', 'vn': None,
                    }
                    success = self.processar_midia(downloaded_file, output_file, **ffmpeg_args)
                    if not success:
                        raise Exception("Falha na conversao FFmpeg")
                    file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
                    duration = info.get('duration', 0)
                    return output_file, file_size, duration, output_format
            except Exception as e:
                raise Exception(f"Erro ao baixar/converter audio: {str(e)}")

        return await loop.run_in_executor(None, _download)

    async def download_batch(self, video_ids: List[str], output_format: str = 'original') -> List[dict]:
        results = []
        for video_id in video_ids:
            try:
                filepath, file_size, duration, ext = await self.download_audio(
                    video_id=video_id, output_format=output_format
                )
                results.append({
                    'video_id': video_id, 'success': True,
                    'filepath': filepath, 'file_size': file_size,
                    'duration': duration, 'ext': ext,
                })
            except Exception as e:
                results.append({
                    'video_id': video_id, 'success': False, 'error': str(e),
                })
        return results