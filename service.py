"""
Serviço para integração com yt-dlp e processamento de áudio.
Responsável por buscar metadados, converter e processar mídia do YouTube.
"""

import asyncio
import os
import uuid
from typing import List, Optional
from pathlib import Path
import yt_dlp
from schemas import VideoMetadata, AudioQuality, DownloadMode


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
    
    def _get_ydl_options_audio(self, quality: AudioQuality, mode: DownloadMode) -> dict:
        """
        Configurações do yt-dlp para download/conversão de áudio.
        Simplificado para melhor compatibilidade com Railway.
        
        Args:
            quality: Qualidade do áudio desejada
            mode: Modo de operação (stream ou download)
            
        Returns:
            Dicionário com configurações do yt-dlp
        """
        # Mapeamento de qualidade para formato
        quality_map = {
            AudioQuality.HIGH: '320',
            AudioQuality.MEDIUM: '192',
            AudioQuality.LOW: '128'
        }
        
        bitrate = quality_map.get(quality, '320')
        
        return {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate,
            }],
            'outtmpl': str(self.download_dir / '%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'keepvideo': False,
            'ignoreerrors': True,
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
    
    async def download_audio(
        self, 
        video_id: str, 
        quality: AudioQuality = AudioQuality.HIGH
    ) -> tuple[str, int, int]:
        """
        Download assíncrono de áudio em MP3.
        
        Args:
            video_id: ID do vídeo
            quality: Qualidade do áudio
            
        Returns:
            Tupla com (caminho do arquivo, tamanho em bytes, duração)
            
        Raises:
            Exception: Erro no download
        """
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        def _download():
            try:
                ydl_opts = self._get_ydl_options_audio(quality, DownloadMode.DOWNLOAD)
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    
                    if info:
                        # Caminho do arquivo baixado
                        filepath = str(self.download_dir / f"{video_id}.mp3")
                        
                        # Tamanho do arquivo
                        file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
                        
                        # Duração
                        duration = info.get('duration', 0)
                        
                        return filepath, file_size, duration
                    
                raise Exception("Não foi possível extrair informações do vídeo")
            except Exception as e:
                raise Exception(f"Erro ao baixar áudio: {str(e)}")
        
        return await loop.run_in_executor(None, _download)
    
    async def stream_audio_to_client(
        self, 
        video_id: str, 
        quality: AudioQuality = AudioQuality.HIGH
    ) -> tuple[str, int]:
        """
        Baixa áudio e retorna caminho do arquivo para streaming.
        
        Args:
            video_id: ID do vídeo
            quality: Qualidade do áudio
            
        Returns:
            Tupla com (caminho do arquivo, duração)
            
        Raises:
            Exception: Erro no download
        """
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        def _download():
            try:
                ydl_opts = self._get_ydl_options_audio(quality, DownloadMode.DOWNLOAD)
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    
                    if info:
                        filepath = str(self.download_dir / f"{video_id}.mp3")
                        
                        if os.path.exists(filepath):
                            duration = info.get('duration', 0)
                            return filepath, duration
                        else:
                            raise Exception("Arquivo não foi criado")
                    
                raise Exception("Não foi possível extrair informações do vídeo")
            except Exception as e:
                raise Exception(f"Erro ao fazer streaming de áudio: {str(e)}")
        
        return await loop.run_in_executor(None, _download)
    
    async def get_audio_stream_info(self, video_id: str) -> dict:
        """
        Obtém informações para streaming de áudio sem download completo.
        Retorna URL de streaming do YouTube para player específico no app.
        
        Args:
            video_id: ID do vídeo
            
        Returns:
            Dicionário com informações de streaming incluindo URL e formato
            
        Raises:
            Exception: Erro ao obter informações
        """
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        def _get_stream_info():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestaudio/best',
                    'extract_flat': False,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    if info:
                        # Encontra a melhor URL de áudio com informações completas
                        audio_url = None
                        audio_format = None
                        audio_codec = None
                        audio_ext = None
                        
                        # Buscar formatos de áudio em ordem de preferência
                        for format in info.get('formats', []):
                            ext = format.get('ext', '')
                            acodec = format.get('acodec', '')
                            vcodec = format.get('vcodec', '')
                            format_url = format.get('url')
                            
                            # Preferir formatos de áudio puro (sem vídeo)
                            if acodec != 'none' and vcodec == 'none':
                                if not audio_url:
                                    audio_url = format_url
                                    audio_format = format.get('format', '')
                                    audio_codec = acodec
                                    audio_ext = ext
                                
                                # Preferir m4a/AAC (mais compatível)
                                if ext == 'm4a' and acodec == 'mp4a.40.2':
                                    audio_url = format_url
                                    audio_format = format.get('format', '')
                                    audio_codec = acodec
                                    audio_ext = ext
                                    break
                        
                        # Se não encontrou áudio puro, busca melhor formato com áudio
                        if not audio_url:
                            for format in info.get('formats', []):
                                if format.get('acodec') != 'none':
                                    audio_url = format.get('url')
                                    audio_format = format.get('format', '')
                                    audio_codec = format.get('acodec', '')
                                    audio_ext = format.get('ext', '')
                                    break
                        
                        # Se ainda não encontrou, usa URL do vídeo
                        if not audio_url:
                            audio_url = url
                            audio_format = 'video'
                            audio_codec = 'unknown'
                            audio_ext = 'mp4'
                        
                        return {
                            'stream_url': audio_url,
                            'duration': info.get('duration', 0),
                            'title': info.get('title', ''),
                            'thumbnail': info.get('thumbnail', ''),
                            'format': audio_format,
                            'codec': audio_codec,
                            'ext': audio_ext,
                            'is_video_url': audio_url == url,
                            'filesize': info.get('filesize', 0) or 0
                        }
                    
                raise Exception("Não foi possível extrair informações de streaming")
            except Exception as e:
                raise Exception(f"Erro ao obter informações de streaming: {str(e)}")
        
        return await loop.run_in_executor(None, _get_stream_info)
    
    async def cleanup_old_files(self, max_age_hours: int = 24):
        """
        Remove arquivos antigos do diretório de downloads.
        
        Args:
            max_age_hours: Idade máxima em horas para manter arquivos
        """
        loop = asyncio.get_event_loop()
        
        def _cleanup():
            try:
                import time
                current_time = time.time()
                max_age_seconds = max_age_hours * 3600
                
                for file_path in self.download_dir.glob('*.mp3'):
                    if file_path.is_file():
                        file_age = current_time - file_path.stat().st_mtime
                        if file_age > max_age_seconds:
                            file_path.unlink()
            except Exception:
                pass  # Silencioso para não interromper operações principais
        
        await loop.run_in_executor(None, _cleanup)
