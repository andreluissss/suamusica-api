"""
Serviço para integração com yt-dlp.
Responsável por buscar metadados e baixar áudio do YouTube.
"""

import asyncio
import os
from typing import List
from pathlib import Path
import yt_dlp
from schemas import VideoMetadata


class YouTubeService:
    """Serviço para interação com YouTube usando yt-dlp."""
    
    def __init__(self, download_dir: str = "./downloads"):
        """
        Inicializa o serviço com diretório de downloads.
        
        Args:
            download_dir: Diretório onde os arquivos serão salvos
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_ydl_options_search(self, max_results: int = 10) -> dict:
        """
        Configurações do yt-dlp para busca.
        
        Args:
            max_results: Número máximo de resultados
            
        Returns:
            Dicionário com configurações do yt-dlp
        """
        return {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlistend': max_results,
            'noplaylist': False,
        }
    
    async def search_videos(self, query: str, max_results: int = 10) -> List[VideoMetadata]:
        """
        Busca vídeos no YouTube de forma assíncrona.
        
        Args:
            query: Termo de busca
            max_results: Número máximo de resultados
            
        Returns:
            Lista de metadados dos vídeos encontrados
            
        Raises:
            Exception: Erro na busca
        """
        loop = asyncio.get_event_loop()
        
        def _search():
            try:
                ydl_opts = self._get_ydl_options_search(max_results)
                
                # Se a query for uma URL direta, extrai metadados
                if query.startswith(('http://', 'https://')):
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(query, download=False)
                        if info:
                            if 'entries' in info:  # Playlist
                                entries = info['entries'][:max_results]
                            else:  # Vídeo único
                                entries = [info]
                            return self._parse_video_info(entries)
                else:
                    # Busca por termo
                    search_url = f'ytsearch{max_results}:{query}'
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(search_url, download=False)
                        if info and 'entries' in info:
                            return self._parse_video_info(info['entries'])
                return []
            except Exception as e:
                raise Exception(f"Erro ao buscar vídeos: {str(e)}")
        
        return await loop.run_in_executor(None, _search)
    
    def _parse_video_info(self, entries: List[dict]) -> List[VideoMetadata]:
        """
        Converte informações brutas do yt-dlp para VideoMetadata.
        
        Args:
            entries: Lista de dicionários com informações do yt-dlp
            
        Returns:
            Lista de VideoMetadata
        """
        videos = []
        for entry in entries:
            if not entry:
                continue
                
            video = VideoMetadata(
                video_id=entry.get('id', ''),
                title=entry.get('title', 'Sem título'),
                thumbnail=entry.get('thumbnail', ''),
                duration=entry.get('duration', 0),
                url=f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                channel=entry.get('channel', entry.get('uploader')),
                view_count=entry.get('view_count'),
                upload_date=entry.get('upload_date')
            )
            videos.append(video)
        
        return videos
    
    async def get_audio_stream_url(self, video_id: str) -> dict:
        """
        Extrai apenas a URL de stream de áudio do YouTube.
        Não baixa arquivo, não usa FFmpeg, apenas retorna a URL direta.
        
        Args:
            video_id: ID do vídeo
            
        Returns:
            Dicionário com stream_url e metadados básicos
            
        Raises:
            Exception: Erro ao extrair URL
        """
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        def _get_stream_url():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'postprocessors': [],
                    'extract_flat': False,
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    if info:
                        # Encontra a melhor URL de áudio
                        audio_url = None
                        audio_format = None
                        audio_ext = None
                        
                        # Busca formatos de áudio puro (sem vídeo)
                        for format in info.get('formats', []):
                            acodec = format.get('acodec', '')
                            vcodec = format.get('vcodec', '')
                            format_url = format.get('url')
                            
                            # Preferir áudio puro (sem vídeo)
                            if acodec != 'none' and vcodec == 'none':
                                if not audio_url:
                                    audio_url = format_url
                                    audio_format = format.get('format', '')
                                    audio_ext = format.get('ext', '')
                                
                                # Preferir m4a/AAC (mais compatível)
                                if format.get('ext') == 'm4a':
                                    audio_url = format_url
                                    audio_format = format.get('format', '')
                                    audio_ext = 'm4a'
                                    break
                        
                        # Se não encontrou áudio puro, usa o melhor com áudio
                        if not audio_url:
                            for format in info.get('formats', []):
                                if format.get('acodec') != 'none' and format.get('url'):
                                    audio_url = format.get('url')
                                    audio_format = format.get('format', '')
                                    audio_ext = format.get('ext', '')
                                    break
                        
                        if audio_url:
                            return {
                                'stream_url': audio_url,
                                'duration': info.get('duration', 0),
                                'title': info.get('title', ''),
                                'thumbnail': info.get('thumbnail', ''),
                                'format': audio_format,
                                'ext': audio_ext,
                            }
                    
                raise Exception("Não foi possível extrair URL de stream")
            except Exception as e:
                raise Exception(f"Erro ao extrair URL de stream: {str(e)}")
        
        return await loop.run_in_executor(None, _get_stream_url)
