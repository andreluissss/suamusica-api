"""
Módulo principal do YouTube Scraper.
Motor completo: busca músicas, playlists, download e streaming de áudio.
Usa yt-dlp (não requer API key).
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from yt_dlp import YoutubeDL


class YouTubeScraper:
    """
    Classe principal para scraping de áudio do YouTube.
    """

    def __init__(self, download_dir: Optional[str] = None):
        self.download_dir = download_dir or os.path.join(
            os.path.expanduser("~"), "YouTubeMusic"
        )
        os.makedirs(self.download_dir, exist_ok=True)

        self.ydl_opts = {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "outtmpl": os.path.join(self.download_dir, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            # Bypass YouTube bot detection usando Android client
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Busca músicas/artistas. Retorna vídeos e playlists.

        Args:
            query: Termo de busca
            max_results: Máximo de resultados

        Returns:
            Lista com type='video' ou type='playlist'
        """
        results = []
        search_query = f"ytsearch{max_results}:{query}"

        try:
            with YoutubeDL({
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
            }) as ydl:
                info = ydl.extract_info(search_query, download=False)

                if info and "entries" in info:
                    for entry in info["entries"]:
                        if not entry:
                            continue

                        entry_type = entry.get("ie_key", "") or entry.get("extractor", "")
                        is_playlist = "playlist" in entry_type.lower() if entry_type else False

                        video = {
                            "id": entry.get("id", ""),
                            "title": entry.get("title", "Sem título"),
                            "channel": entry.get("channel", entry.get("uploader", "Desconhecido")),
                            "duration": self._format_duration(entry.get("duration", 0)),
                            "duration_seconds": entry.get("duration", 0),
                            "views": entry.get("view_count", 0),
                            "type": "playlist" if is_playlist else "video",
                            "url": (
                                f"https://www.youtube.com/playlist?list={entry.get('id')}"
                                if is_playlist
                                else f"https://www.youtube.com/watch?v={entry.get('id', '')}"
                            ),
                            "thumbnail": (
                                entry.get("thumbnails", [{}])[0].get("url", "")
                                if entry.get("thumbnails")
                                else ""
                            ),
                        }
                        results.append(video)

            return results

        except Exception as e:
            raise Exception(f"Erro na busca: {str(e)}")

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
        Extrai as faixas individuais de uma playlist.
        Cada faixa é um áudio separado (não um único arquivo).

        Args:
            playlist_url: URL da playlist do YouTube

        Returns:
            Lista de dicionários com cada música da playlist
        """
        tracks = []
        try:
            with YoutubeDL({
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "playlistend": 50,  # Limite de 50 músicas
            }) as ydl:
                info = ydl.extract_info(playlist_url, download=False)

                playlist_title = info.get("title", "Playlist sem nome")
                entries = info.get("entries", [])

                for entry in entries:
                    if not entry:
                        continue

                    track = {
                        "id": entry.get("id", ""),
                        "title": entry.get("title", "Sem título"),
                        "channel": entry.get("channel", entry.get("uploader", "Desconhecido")),
                        "duration": self._format_duration(entry.get("duration", 0)),
                        "duration_seconds": entry.get("duration", 0),
                        "type": "track",
                        "url": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                        "playlist": playlist_title,
                    }
                    tracks.append(track)

            return tracks

        except Exception as e:
            raise Exception(f"Erro ao obter faixas da playlist: {str(e)}")

    def download_audio(self, video_url: str, filename: Optional[str] = None) -> str:
        """
        Baixa o áudio como MP3.

        Args:
            video_url: URL do vídeo
            filename: Nome personalizado (opcional)

        Returns:
            Caminho do arquivo MP3
        """
        opts = dict(self.ydl_opts)

        if filename:
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)[:100]
            file_path = os.path.join(self.download_dir, f"{safe_name}.%(ext)s")
            opts["outtmpl"] = file_path

        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                title = info.get("title", "audio_downloaded")

                expected_file = os.path.join(
                    self.download_dir,
                    f"{filename or title}.mp3",
                )

                if os.path.exists(expected_file):
                    return expected_file

                mp3_files = sorted(
                    Path(self.download_dir).glob("*.mp3"),
                    key=os.path.getmtime,
                    reverse=True,
                )
                if mp3_files:
                    return str(mp3_files[0])

                return expected_file

        except Exception as e:
            raise Exception(f"Erro ao baixar áudio: {str(e)}")

    def get_audio_stream_url(self, video_url: str) -> Tuple[str, str]:
        """
        Obtém URL direta do stream de áudio.

        Returns:
            Tupla (url_stream, titulo)
        """
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "format": "bestaudio/best",
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            }
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                audio_url = info.get("url", "")
                title = info.get("title", "Sem título")

                formats = info.get("formats", [])
                audio_formats = [
                    f for f in formats
                    if f.get("vcodec") == "none" and f.get("acodec") != "none"
                ]

                if audio_formats:
                    best_audio = max(
                        audio_formats,
                        key=lambda f: f.get("abr", 0) or 0,
                    )
                    audio_url = best_audio.get("url", audio_url)

                return audio_url, title

        except Exception as e:
            raise Exception(f"Erro ao obter stream: {str(e)}")

    def get_video_info(self, video_url: str) -> Dict:
        """Obtém informações detalhadas do vídeo."""
        try:
            with YoutubeDL({"quiet": True, "no_warnings": True, "extractor_args": {"youtube": {"player_client": ["android", "web"]}}}) as ydl:
                info = ydl.extract_info(video_url, download=False)

                audio_formats = []
                for f in info.get("formats", []):
                    if f.get("vcodec") == "none" and f.get("acodec") != "none":
                        audio_formats.append({
                            "format_id": f.get("format_id"),
                            "ext": f.get("ext"),
                            "filesize": f.get("filesize"),
                            "abr": f.get("abr"),
                        })

                return {
                    "id": info.get("id", ""),
                    "title": info.get("title", "Sem título"),
                    "channel": info.get("channel", info.get("uploader", "Desconhecido")),
                    "duration": self._format_duration(info.get("duration", 0)),
                    "duration_seconds": info.get("duration", 0),
                    "view_count": info.get("view_count", 0),
                    "like_count": info.get("like_count", 0),
                    "thumbnail": info.get("thumbnail", ""),
                    "audio_formats": audio_formats,
                    "description": (info.get("description") or "")[:300],
                    "is_playlist": info.get("extractor", "").lower().find("playlist") >= 0,
                    "url": video_url,
                }
        except Exception as e:
            raise Exception(f"Erro ao obter info: {str(e)}")

    def list_downloaded(self) -> List[Dict]:
        """Lista todos os MP3s baixados."""
        downloaded = []
        for f in Path(self.download_dir).glob("*.mp3"):
            stats = os.stat(f)
            downloaded.append({
                "filename": f.name,
                "path": str(f),
                "size_mb": round(stats.st_size / (1024 * 1024), 2),
                "modified": stats.st_mtime,
            })
        return sorted(downloaded, key=lambda x: x["modified"], reverse=True)

    def download_playlist_audios(self, playlist_url: str) -> List[str]:
        """
        Baixa todas as músicas de uma playlist como arquivos MP3 separados.

        Args:
            playlist_url: URL da playlist

        Returns:
            Lista de caminhos dos arquivos baixados
        """
        tracks = self.get_playlist_tracks(playlist_url)
        downloaded_files = []

        for track in tracks:
            print(f"  ⬇ {track['title']}...")
            try:
                filepath = self.download_audio(
                    track["url"],
                    filename=f"{track['channel']} - {track['title']}"[:100]
                )
                downloaded_files.append(filepath)
                print(f"    ✅ OK")
            except Exception as e:
                print(f"    ❌ {e}")

        return downloaded_files

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