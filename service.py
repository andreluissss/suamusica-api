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

import subprocess
import json


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
    
    def _get_audio_from_formats(self, info):
        """Extrai o melhor formato de áudio das informações do vídeo."""
        formats = info.get('formats', [])
        audio_formats = [
            f for f in formats 
            if f.get('acodec') != 'none' and f.get('url')
            and f.get('protocol') in ('https', 'http')
        ]
        audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
        if audio_formats:
            best = audio_formats[0]
            return {
                'stream_url': best.get('url'),
                'duration': info.get('duration', 0),
                'title': info.get('title', ''),
                'thumbnail': info.get('thumbnail', ''),
                'format': best.get('format', ''),
                'ext': best.get('ext', ''),
            }
        return None

    async def get_audio_stream_url(self, video_id: str) -> dict:
        """
        Extrai a URL de stream de áudio crua do YouTube.
        Tenta múltiplos extractors e clientes para evitar bloqueio.
        Não baixa nada no servidor, apenas retorna a URL direta do áudio (m4a, webm, etc.).
        """
        loop = asyncio.get_event_loop()
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        def _get_stream_url():
            # Tenta múltiplas estratégias em sequência
            strategies = [
                # 1) Android TV client (menos restritivo)
                {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'extract_flat': False,
                    'user_agent': 'Mozilla/5.0 (Linux; Android 12; SM-T500) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                    'extractor_args': {'youtube': {'player_client': ['android_tv'], 'skip': ['webpage', 'dash', 'hls']}},
                },
                # 2) iOS
                {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'extract_flat': False,
                    'user_agent': 'com.google.ios.youtube/19.45.3 (iPhone14,3; U; CPU iOS 17_5_1 like Mac OS X)',
                    'extractor_args': {'youtube': {'player_client': ['ios'], 'skip': ['webpage', 'dash', 'hls']}},
                },
                # 3) Android
                {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'extract_flat': False,
                    'user_agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36',
                    'extractor_args': {'youtube': {'player_client': ['android', 'android_embedded'], 'skip': ['webpage', 'dash', 'hls']}},
                },
                # 4) Web creator
                {
                    'quiet': True, 
                    'no_warnings': True,
                    'download': False,
                    'extract_flat': False,
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                    'extractor_args': {'youtube': {'player_client': ['web_creator'], 'skip': ['webpage', 'dash', 'hls']}},
                },
                # 5) TV HTML5
                {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'extract_flat': False,
                    'user_agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/537.36',
                    'extractor_args': {'youtube': {'player_client': ['tv'], 'skip': ['webpage', 'dash', 'hls']}},
                },
            ]
            
            last_error = None
            for opts in strategies:
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if info:
                            result = self._get_audio_from_formats(info)
                            if result:
                                return result
                except Exception as e:
                    last_error = str(e)
                    if 'Sign in' in str(e) or 'bot' in str(e).lower():
                        continue
                    raise
            
            # Último recurso: tenta com formato básico
            try:
                basic_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'download': False,
                    'extract_flat': False,
                    'format': 'bestaudio[protocol^=http]',
                }
                with yt_dlp.YoutubeDL(basic_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        url_audio = info.get('url', '')
                        if url_audio:
                            return {
                                'stream_url': url_audio,
                                'duration': info.get('duration', 0),
                                'title': info.get('title', ''),
                                'thumbnail': info.get('thumbnail', ''),
                                'format': '',
                                'ext': info.get('ext', 'm4a'),
                            }
            except Exception as e:
                last_error = str(e)
            
            raise Exception(f"Todas as estratégias falharam. Último erro: {last_error}")
        
        return await loop.run_in_executor(None, _get_stream_url)
    
    def processar_midia(
        self, 
        caminho_entrada: str, 
        caminho_saida: str, 
        **kwargs
    ) -> bool:
        """
        Processa mídia usando FFmpeg via subprocess com tratamento de erros robusto.
        
        Args:
            caminho_entrada: Caminho do arquivo de entrada
            caminho_saida: Caminho do arquivo de saída
            **kwargs: Argumentos adicionais para FFmpeg (codec, bitrate, etc.)
        
        Returns:
            True se processamento bem-sucedido, False caso contrário
        """
        try:
            print(f"[FFmpeg] Processando: {caminho_entrada} -> {caminho_saida}")
            
            # Constrói comando FFmpeg via subprocess
            cmd = ['ffmpeg', '-i', caminho_entrada]
            
            # Mapeia kwargs para argumentos FFmpeg
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
            
            # Executa o processamento
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutos timeout
            )
            
            if result.returncode != 0:
                print(f"[FFmpeg] Erro no processamento: {result.stderr}")
                return False
            
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
                
        except subprocess.TimeoutExpired:
            print(f"[FFmpeg] Erro: Timeout no processamento")
            return False
        except FileNotFoundError:
            print(f"[FFmpeg] Erro: FFmpeg não encontrado no sistema. Instale ffmpeg ou use Docker.")
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