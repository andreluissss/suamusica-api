"""
Servico para integracao com yt-dlp.
Responsavel por buscar metadados e baixar audio do YouTube.
"""

import asyncio
import os
from typing import List, Optional, Tuple
from pathlib import Path
import yt_dlp
from schemas import VideoMetadata, PlaylistMetadata
import subprocess


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
        q = query.lower().strip()
        if any(kw in q for kw in ['playlist', 'setlist', 'podcast', 'album completo', 'full album', 'discografia', 'coletanea']):
            return 'playlist'
        if q in self._KNOWN_ARTISTS:
            return 'artist'
        for a in self._KNOWN_ARTISTS:
            if a in q:
                return 'artist'
        if ' - ' in query:
            return 'music'
        words = q.split()
        if 1 <= len(words) <= 3 and not any(w in self._COMMON_WORDS for w in words):
            return 'artist'
        if any(ma in q for ma in ['ouvir', 'ouca', 'escutar', 'tocar', 'play', 'musica', 'song', 'track']):
            return 'music'
        return 'general'

    def _build_intelligent_query(self, query: str, search_type: str) -> str:
        if search_type == 'artist':
            return f'"{query}" musica oficial'
        return query

    def _is_artist_or_band_query(self, query: str) -> bool:
        q = query.lower().strip()
        if q in self._KNOWN_ARTISTS:
            return True
        for a in self._KNOWN_ARTISTS:
            if len(a.split()) >= 2 and a in q:
                return True
        return False

    def _filter_by_artist(self, entries: List[dict], artist_name: str) -> List[dict]:
        al = artist_name.lower().strip()
        filtered = []
        for e in entries:
            if not e:
                continue
            ch = (e.get('channel', '') or e.get('uploader', '') or '').lower()
            ti = (e.get('title', '') or '').lower()
            if al in ch or al in ti or all(p in ti for p in al.split()) or all(p in ch for p in al.split()):
                filtered.append(e)
        return filtered if filtered else entries

    def _get_ydl_opts(self, extract_flat=True, max_results=10) -> dict:
        """Opcoes base do yt-dlp com headers anti-bloqueio."""
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': extract_flat,
            'noplaylist': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
            },
        }
        if extract_flat:
            opts['playlistend'] = max_results * 3
        return opts

    async def search_videos(self, query: str, max_results: int = 10,
                           mode: str = 'listen', include_playlists: bool = True,
                           type_filter: str = 'auto') -> Tuple[List[VideoMetadata], List[PlaylistMetadata], str]:
        search_type = type_filter if type_filter != 'auto' else self._detect_search_type(query)
        intelligent_query = self._build_intelligent_query(query, search_type)
        loop = asyncio.get_event_loop()

        def _search():
            try:
                videos = []
                playlists = []

                if query.startswith(('http://', 'https://')):
                    with yt_dlp.YoutubeDL(self._get_ydl_opts(True, max_results)) as ydl:
                        info = ydl.extract_info(query, download=False)
                        if info:
                            if 'entries' in info:
                                entries = info['entries'][:max_results]
                                playlists.append(PlaylistMetadata(
                                    playlist_id=info.get('id', ''),
                                    title=info.get('title', 'Playlist'),
                                    thumbnail=info.get('thumbnail', ''),
                                    channel=info.get('channel', info.get('uploader')),
                                    video_count=len(entries),
                                    url=f"https://www.youtube.com/playlist?list={info.get('id', '')}"
                                ))
                                videos = self._parse_video_info(entries)
                            else:
                                videos = self._parse_video_info([info])
                else:
                    search_url = f'ytsearch{max_results * 2}:{intelligent_query}'
                    with yt_dlp.YoutubeDL(self._get_ydl_opts(True, max_results)) as ydl:
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
                                is_pl = entry.get('_type', '') == 'playlist' or 'playlist' in ie_key.lower() or entry.get('playlist_id')
                                if is_pl and include_playlists:
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
                            with yt_dlp.YoutubeDL(self._get_ydl_opts(True, max_results)) as ydl:
                                pl_info = ydl.extract_info(f'ytsearch{max_results}:{query} playlist', download=False)
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

                if mode == 'listen' and videos:
                    try:
                        videos = self._attach_stream_urls(videos)
                    except Exception:
                        pass
                elif mode == 'download' and videos:
                    try:
                        videos = self._attach_download_urls(videos)
                    except Exception:
                        pass

                return videos, playlists, search_type
            except Exception as e:
                raise Exception(f"Erro ao buscar videos: {str(e)}")

        return await loop.run_in_executor(None, _search)

    def _get_audio_url_ytdlp(self, video_id: str) -> Optional[str]:
        """Obtem URL de audio usando yt-dlp (estrategia PRINCIPAL - funciona localmente)."""
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            opts = self._get_ydl_opts(extract_flat=False)
            opts['format'] = 'bestaudio/best'
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    formats = info.get('formats', [])
                    audio = [f for f in formats if f.get('acodec') != 'none' and f.get('url')]
                    if audio:
                        audio.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                        return audio[0].get('url')
        except Exception:
            pass
        return None

    def _get_audio_url_api(self, video_id: str) -> Optional[str]:
        """Fallback: YouTube API Android."""
        try:
            import requests as req
            import urllib.parse
            api_keys = ["AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"]
            clients = [
                {"clientName": "ANDROID", "clientVersion": "19.09.37"},
                {"clientName": "WEB", "clientVersion": "2.20240701.00.00"},
            ]
            for key in api_keys:
                for client in clients:
                    try:
                        r = req.post(f"https://www.youtube.com/youtubei/v1/player?key={key}",
                            json={"context": {"client": client}, "videoId": video_id},
                            headers={"Content-Type": "application/json"}, timeout=10)
                        if r.status_code == 200:
                            data = r.json()
                            for fmt in data.get('streamingData', {}).get('adaptiveFormats', []):
                                mime = fmt.get('mimeType', '')
                                if mime.startswith('audio/'):
                                    url = fmt.get('url', '')
                                    if url:
                                        return url
                                    cipher = fmt.get('signatureCipher', '') or fmt.get('cipher', '')
                                    if cipher:
                                        parsed = urllib.parse.parse_qs(cipher)
                                        url = parsed.get('url', [''])[0]
                                        if url:
                                            return url
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    def _attach_stream_urls(self, videos: List[VideoMetadata]) -> List[VideoMetadata]:
        for v in videos:
            if v.video_id:
                try:
                    url = self._get_audio_url_ytdlp(v.video_id)
                    if url:
                        v.stream_url = url
                except Exception:
                    pass
        return videos

    def _attach_download_urls(self, videos: List[VideoMetadata]) -> List[VideoMetadata]:
        for v in videos:
            if v.video_id:
                try:
                    url = self._get_audio_url_ytdlp(v.video_id)
                    if url:
                        v.stream_url = url
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
            videos.append(VideoMetadata(
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
            ))
        return videos

    async def get_playlist_items(self, playlist_id: str, max_results: int = 50) -> Tuple[str, str, Optional[str], int, List[VideoMetadata]]:
        loop = asyncio.get_event_loop()
        playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

        def _extract():
            opts = self._get_ydl_opts(extract_flat='in_playlist')
            opts['playlistend'] = max_results
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                if not info:
                    raise Exception("Playlist nao encontrada")
                entries = info.get('entries', []) or []
                videos = self._parse_video_info(entries)
                return info.get('title', 'Playlist'), playlist_url, info.get('channel', info.get('uploader')), len(entries), videos

        return await loop.run_in_executor(None, _extract)

    async def get_audio_stream_url(self, video_id: str) -> dict:
        """Obtem URL de stream de audio. yt-dlp principal, API fallback."""
        loop = asyncio.get_event_loop()

        def _get():
            # 1. yt-dlp (principal - funciona)
            try:
                url = self._get_audio_url_ytdlp(video_id)
                if url:
                    return {'stream_url': url, 'duration': 0, 'title': '', 'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg', 'format': '', 'ext': ''}
            except Exception:
                pass
            # 2. API fallback
            try:
                url = self._get_audio_url_api(video_id)
                if url:
                    return {'stream_url': url, 'duration': 0, 'title': '', 'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg', 'format': '', 'ext': ''}
            except Exception:
                pass
            return {'stream_url': None, 'duration': 0, 'title': '', 'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg', 'format': '', 'ext': ''}

        return await loop.run_in_executor(None, _get)

    async def get_direct_download_url(self, video_id: str) -> dict:
        """Obtem URL de download direto. yt-dlp principal, API fallback."""
        loop = asyncio.get_event_loop()

        def _get():
            try:
                url = self._get_audio_url_ytdlp(video_id)
                if url:
                    return {'download_url': url, 'ext': 'm4a', 'title': '', 'duration': 0, 'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'}
            except Exception:
                pass
            try:
                url = self._get_audio_url_api(video_id)
                if url:
                    return {'download_url': url, 'ext': 'm4a', 'title': '', 'duration': 0, 'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'}
            except Exception:
                pass
            return {'download_url': None, 'ext': 'unknown', 'title': '', 'duration': 0, 'thumbnail': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'}

        return await loop.run_in_executor(None, _get)

    def processar_midia(self, entrada: str, saida: str, **kwargs) -> bool:
        try:
            cmd = ['ffmpeg', '-i', entrada]
            for k, v in kwargs.items():
                if k == 'acodec': cmd.extend(['-acodec', str(v)])
                elif k == 'ab': cmd.extend(['-ab', str(v)])
                elif k == 'vn' and v is None: cmd.append('-vn')
                else: cmd.extend([f'-{k}', str(v)])
            cmd.extend(['-y', saida])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if r.returncode != 0 or not os.path.exists(saida):
                return False
            if os.path.exists(entrada):
                os.remove(entrada)
            return True
        except Exception:
            return False

    async def download_audio(self, video_id: str, output_format: str = 'original') -> tuple:
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"

        def _download():
            opts = {'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True,
                    'outtmpl': str(self.download_dir / f'{video_id}.%(ext)s')}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise Exception("Falha ao baixar")
                for ext in ['m4a', 'webm', 'mp4', 'opus', 'ogg']:
                    f = self.download_dir / f"{video_id}.{ext}"
                    if f.exists():
                        if output_format == 'original':
                            return str(f), os.path.getsize(str(f)), info.get('duration', 0), ext
                        saida = str(self.download_dir / f"{video_id}.{output_format}")
                        args = {'acodec': 'libmp3lame' if output_format == 'mp3' else 'aac', 'ab': '192k', 'vn': None}
                        if self.processar_midia(str(f), saida, **args):
                            return saida, os.path.getsize(saida) if os.path.exists(saida) else 0, info.get('duration', 0), output_format
                raise Exception("Arquivo nao encontrado")

        return await loop.run_in_executor(None, _download)

    async def download_batch(self, video_ids: List[str], output_format: str = 'original') -> List[dict]:
        results = []
        for vid in video_ids:
            try:
                fp, fs, dur, ext = await self.download_audio(vid, output_format)
                results.append({'video_id': vid, 'success': True, 'filepath': fp, 'file_size': fs, 'duration': dur, 'ext': ext})
            except Exception as e:
                results.append({'video_id': vid, 'success': False, 'error': str(e)})
        return results