"""
Serviço para integração com yt-dlp.
Responsável por buscar metadados e baixar áudio do YouTube.
"""

import asyncio
import os
from typing import List, Optional
from pathlib import Path
import yt_dlp
from schemas import VideoMetadata

# Instalação automática do FFmpeg
try:
    from static_ffmpeg import add_paths
    add_paths()
except ImportError:
    pass

import ffmpeg


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
        Extrai a URL de stream de áudio crua do YouTube.
        Não usa FFmpeg, não converte, apenas retorna a URL direta do arquivo de áudio.
        
        Args:
            video_id: ID do vídeo
            
        Returns:
            Dicionário com stream_url de áudio e metadados
        """
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        def _get_stream_url():
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'extract_flat': False,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    if info:
                        # Pega o primeiro formato de áudio disponível
                        for format in info.get('formats', []):
                            if format.get('acodec') != 'none' and format.get('url'):
                                return {
                                    'stream_url': format.get('url'),
                                    'duration': info.get('duration', 0),
                                    'title': info.get('title', ''),
                                    'thumbnail': info.get('thumbnail', ''),
                                    'format': format.get('format', ''),
                                    'ext': format.get('ext', ''),
                                }
                    
                raise Exception("Não foi possível extrair URL de áudio")
            except Exception as e:
                raise Exception(f"Erro ao extrair URL de áudio: {str(e)}")
        
        return await loop.run_in_executor(None, _get_stream_url)
    
    def processar_midia(
        self, 
        caminho_entrada: str, 
        caminho_saida: str, 
        **kwargs
    ) -> bool:
        """
        Processa mídia usando FFmpeg com tratamento de erros robusto.
        
        Args:
            caminho_entrada: Caminho do arquivo de entrada
            caminho_saida: Caminho do arquivo de saída
            **kwargs: Argumentos adicionais para FFmpeg (codec, bitrate, etc.)
        
        Returns:
            True se processamento bem-sucedido, False caso contrário
        """
        try:
            print(f"[FFmpeg] Processando: {caminho_entrada} -> {caminho_saida}")
            
            # Constrói o pipeline FFmpeg
            input_stream = ffmpeg.input(caminho_entrada)
            
            # Aplica argumentos adicionais se fornecidos
            output_stream = input_stream.output(caminho_saida, **kwargs)
            
            # Executa o processamento
            ffmpeg.run(output_stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)
            
            # Verifica se o arquivo de saída foi criado
            if os.path.exists(caminho_saida):
                print(f"[FFmpeg] Processamento concluído com sucesso: {caminho_saida}")
                
                # Deleta arquivo original após conversão bem-sucedida
                if os.path.exists(caminho_entrada):
                    os.remove(caminho_entrada)
                    print(f"[FFmpeg] Arquivo original deletado: {caminho_entrada}")
                
                return True
            else:
                print(f"[FFmpeg] Erro: Arquivo de saída não foi criado")
                return False
                
        except ffmpeg.Error as e:
            print(f"[FFmpeg] Erro no processamento: {e.stderr.decode('utf8') if e.stderr else str(e)}")
            return False
        except Exception as e:
            print(f"[FFmpeg] Erro inesperado: {str(e)}")
            return False
    
    async def download_audio(self, video_id: str, output_format: str = 'mp3') -> tuple[str, int, int]:
        """
        Baixa áudio do YouTube e converte usando FFmpeg.
        
        Args:
            video_id: ID do vídeo
            output_format: Formato de saída (mp3, m4a, etc.)
            
        Returns:
            Tupla com (caminho do arquivo, tamanho em bytes, duração)
            
        Raises:
            Exception: Erro no download ou conversão
        """
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        def _download():
            try:
                # Baixa áudio no formato original
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
                    
                    # Encontra o arquivo baixado
                    downloaded_file = None
                    for ext in ['m4a', 'webm', 'mp4']:
                        test_file = self.download_dir / f"{video_id}.{ext}"
                        if test_file.exists():
                            downloaded_file = str(test_file)
                            break
                    
                    if not downloaded_file:
                        raise Exception("Arquivo baixado não encontrado")
                    
                    # Converte para o formato desejado
                    output_file = str(self.download_dir / f"{video_id}.{output_format}")
                    
                    # Argumentos FFmpeg para conversão de áudio
                    ffmpeg_args = {
                        'acodec': 'libmp3lame' if output_format == 'mp3' else 'aac',
                        'ab': '192k',
                        'vn': None,  # Sem vídeo
                    }
                    
                    success = self.processar_midia(downloaded_file, output_file, **ffmpeg_args)
                    
                    if not success:
                        raise Exception("Falha na conversão FFmpeg")
                    
                    # Retorna informações do arquivo convertido
                    file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
                    duration = info.get('duration', 0)
                    
                    return output_file, file_size, duration
                    
            except Exception as e:
                raise Exception(f"Erro ao baixar/converter áudio: {str(e)}")
        
        return await loop.run_in_executor(None, _download)
