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
    
    async def get_audio_stream_url(self, video_id: str) -> dict:
        """
        Extrai a URL de stream de áudio crua do YouTube.
        Usa requests para acessar diretamente o endpoint de video info do YouTube
        (mesma abordagem do pytube), sem depender de yt-dlp.
        Não baixa nada no servidor, apenas retorna a URL direta do áudio (m4a, webm, etc.).
        """
        import requests as sync_requests
        import re
        import json
        loop = asyncio.get_event_loop()
        
        def _extract_audio_urls(player_response):
            """Extrai URLs de áudio do player_response do YouTube"""
            urls = []
            
            # Tenta extrair de streamingData
            streaming_data = player_response.get('streamingData', {})
            
            # Formatos adaptativos (áudio puro)
            for fmt in streaming_data.get('adaptiveFormats', []):
                mime = fmt.get('mimeType', '')
                if mime.startswith('audio/'):
                    url = fmt.get('url') or fmt.get('signatureCipher', '')
                    if url:
                        urls.append({
                            'url': url,
                            'abr': fmt.get('averageBitrate', fmt.get('bitrate', 0)),
                            'mime': mime,
                            'ext': mime.split('/')[-1].split(';')[0],
                            'quality': fmt.get('qualityLabel', ''),
                        })
            
            # Formatos normais (podem ter áudio)
            for fmt in streaming_data.get('formats', []):
                mime = fmt.get('mimeType', '')
                if mime.startswith('audio/') or True:  # Pega todos com audio
                    acodec = fmt.get('audioChannels', 0)
                    if acodec > 0:
                        url = fmt.get('url') or fmt.get('signatureCipher', '')
                        if url:
                            urls.append({
                                'url': url,
                                'abr': fmt.get('averageBitrate', fmt.get('bitrate', 0)),
                                'mime': mime,
                                'ext': mime.split('/')[-1].split(';')[0],
                                'quality': fmt.get('qualityLabel', ''),
                            })
            
            return urls

        def _fetch_direct():
            """Acessa diretamente o YouTube para extrair URLs de áudio"""
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
            }
            
            # Tenta obter a página do vídeo
            watch_url = f'https://www.youtube.com/watch?v={video_id}'
            resp = sync_requests.get(watch_url, headers=headers, timeout=15)
            
            if resp.status_code != 200:
                raise Exception(f"Falha ao acessar YouTube: HTTP {resp.status_code}")
            
            # Extrai o ytInitialPlayerResponse dos dados da página
            # Padrão: ytInitialPlayerResponse = {...};
            match = re.search(r'ytInitialPlayerResponse\s*=\s*({.*?});', resp.text, re.DOTALL)
            if not match:
                raise Exception("Não foi possível extrair player response da página")
            
            player_data = json.loads(match.group(1))
            
            # Extrai metadados
            video_details = player_data.get('videoDetails', {})
            title = video_details.get('title', '')
            duration = int(video_details.get('lengthSeconds', 0))
            thumbnail = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'
            
            # Extrai URLs de áudio
            audio_urls = _extract_audio_urls(player_data)
            
            if not audio_urls:
                raise Exception("Nenhum formato de áudio encontrado")
            
            # Pega o melhor (maior bitrate)
            best = max(audio_urls, key=lambda x: x.get('abr', 0) or 0)
            
            return {
                'stream_url': best['url'],
                'duration': duration,
                'title': title,
                'thumbnail': thumbnail,
                'format': best.get('quality', ''),
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
                except:
                    continue
            return None

        def _get_stream_url():
            # 1. Tenta extração direta (mesmo método do pytube)
            try:
                return _fetch_direct()
            except Exception:
                pass
            
            # 2. Tenta yt-dlp
            result = _fetch_from_ytdlp()
            if result:
                return result
            
            # 3. Tenta Piped
            result = _fetch_from_piped()
            if result:
                return result
            
            raise Exception("Todas as fontes falharam")

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
                    for ext in ['m4a', 'webm', 'mp4']:
                        test_file = self.download_dir / f"{video_id}.{ext}"
                        if test_file.exists():
                            downloaded_file = str(test_file)
                            break
                    
                    if not downloaded_file:
                        raise Exception("Arquivo baixado não encontrado")
                    
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
                    
                    return output_file, file_size, duration
                    
            except Exception as e:
                raise Exception(f"Erro ao baixar/converter áudio: {str(e)}")
        
        return await loop.run_in_executor(None, _download)