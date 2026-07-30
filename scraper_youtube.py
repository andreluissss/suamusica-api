"""
YouTube Scraper - Extrai metadados de vídeos/playlist/canais via yt-dlp
Uso: python scraper_youtube.py --url "https://www.youtube.com/watch?v=..."
"""

import os
import re
import time
import logging
import hashlib
import subprocess
from typing import List, Dict, Optional
from supabase import create_client, Client
from dotenv import load_dotenv
import yt_dlp

# Carrega variáveis de ambiente
load_dotenv()

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class YouTubeScraper:
    """Scraper que extrai metadados de vídeos do YouTube via yt-dlp"""

    BATCH_SIZE = 50

    def __init__(self):
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")
        
        self.supabase: Client = create_client(supabase_url, supabase_key)
        self.processed_video_ids = set()
        
        # Configurações anti-bot para simular navegador real
        self.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }
    
    def _get_ydl_opts(self, base_opts=None):
        """Retorna opções do yt-dlp com configurações anti-bot"""
        opts = base_opts.copy() if base_opts else {}
        
        # Adiciona configurações anti-bot
        opts.update({
            'user_agent': self.user_agent,
            'http_headers': self.headers,
            'nocheckcertificate': True,  # Ignora erros de certificado SSL
            'ignoreerrors': True,  # Continua mesmo com erros
            'quiet': True,
            'no_warnings': True,
        })
        
        # Adiciona cookies se arquivo existir
        cookie_file = os.getenv('YOUTUBE_COOKIES_FILE', 'cookies.txt')
        if os.path.exists(cookie_file):
            opts['cookiefile'] = cookie_file
            logger.info(f"Usando cookies de: {cookie_file}")
        
        return opts

    def _extract_video_info(self, url: str) -> Optional[Dict]:
        """Extrai metadados de um vídeo específico"""
        ydl_opts = self._get_ydl_opts({'extract_flat': False})
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Extrai o melhor formato de áudio
                formats = info.get('formats', [])
                audio_formats = [f for f in formats if f.get('acodec') != 'none']
                best_audio = audio_formats[0] if audio_formats else None
                
                return {
                    'video_id': info.get('id'),
                    'title': info.get('title', ''),
                    'uploader': info.get('uploader', ''),
                    'uploader_id': info.get('uploader_id', ''),
                    'duration': info.get('duration', 0),
                    'view_count': info.get('view_count', 0),
                    'upload_date': info.get('upload_date', ''),
                    'description': info.get('description', '')[:500],
                    'thumbnail': info.get('thumbnail', ''),
                    'url': url,
                    'audio_url': best_audio.get('url', '') if best_audio else None,
                    'audio_format': best_audio.get('format', '') if best_audio else None,
                }
        except Exception as e:
            logger.error(f"Erro ao extrair vídeo {url}: {e}")
            return None

    def get_audio_stream_url(self, url: str) -> Optional[str]:
        """Retorna URL de stream de áudio de um vídeo"""
        ydl_opts = self._get_ydl_opts({'format': 'bestaudio/best'})
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get('formats', [])
                audio_formats = [f for f in formats if f.get('acodec') != 'none']
                
                if audio_formats:
                    # Retorna o melhor formato de áudio
                    return audio_formats[0].get('url', '')
                
                return None
        except Exception as e:
            logger.error(f"Erro ao obter stream de áudio: {e}")
            return None

    def download_audio(self, url: str, output_path: str = None) -> Optional[str]:
        """Baixa áudio de um vídeo"""
        if output_path is None:
            output_path = 'downloads'
        
        # Cria diretório se não existir
        os.makedirs(output_path, exist_ok=True)
        
        ydl_opts = self._get_ydl_opts({
            'format': 'bestaudio/best',
            'outtmpl': f'{output_path}/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
                logger.info(f"✅ Áudio baixado: {filename}")
                return filename
        except Exception as e:
            logger.error(f"Erro ao baixar áudio: {e}")
            return None

    def play_audio(self, url: str) -> bool:
        """Toca áudio de um vídeo usando player do sistema"""
        try:
            # Tenta obter URL de stream
            audio_url = self.get_audio_stream_url(url)
            
            if not audio_url:
                logger.error("Não foi possível obter URL de áudio")
                return False
            
            logger.info(f"🎵 Tocando áudio: {audio_url}")
            
            # Tenta abrir com player padrão do sistema
            if os.name == 'nt':  # Windows
                os.startfile(audio_url)
            elif os.name == 'posix':  # Linux/Mac
                subprocess.call(['xdg-open', audio_url])
            
            return True
        except Exception as e:
            logger.error(f"Erro ao tocar áudio: {e}")
            return False

    def _extract_playlist_info(self, url: str) -> List[Dict]:
        """Extrai metadados de todos os vídeos de uma playlist"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'ignoreerrors': True,
        }
        
        videos = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry and entry.get('id'):
                            video_id = entry.get('id')
                            if video_id not in self.processed_video_ids:
                                video_data = {
                                    'video_id': video_id,
                                    'title': entry.get('title', ''),
                                    'uploader': entry.get('uploader', ''),
                                    'uploader_id': entry.get('uploader_id', ''),
                                    'duration': entry.get('duration', 0),
                                    'view_count': entry.get('view_count', 0),
                                    'upload_date': entry.get('upload_date', ''),
                                    'url': entry.get('webpage_url', ''),
                                    'thumbnail': entry.get('thumbnail', ''),
                                }
                                videos.append(video_data)
                                self.processed_video_ids.add(video_id)
                
                logger.info(f"Playlist: {len(videos)} vídeos extraídos")
                return videos
                
        except Exception as e:
            logger.error(f"Erro ao extrair playlist {url}: {e}")
            return []

    def search_music(self, query: str, limit: int = 10) -> List[Dict]:
        """Pesquisa músicas no YouTube"""
        search_query = f"ytsearch{limit}:{query}"
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        results = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry and entry.get('id'):
                            video_data = {
                                'video_id': entry.get('id'),
                                'title': entry.get('title', ''),
                                'uploader': entry.get('uploader', ''),
                                'uploader_id': entry.get('uploader_id', ''),
                                'duration': entry.get('duration', 0),
                                'view_count': entry.get('view_count', 0),
                                'url': entry.get('webpage_url', ''),
                                'thumbnail': entry.get('thumbnail', ''),
                            }
                            results.append(video_data)
                
                logger.info(f"Pesquisa música: {len(results)} resultados encontrados")
                return results
                
        except Exception as e:
            logger.error(f"Erro ao pesquisar música '{query}': {e}")
            return []

    def search_playlists(self, query: str, limit: int = 10, separated_only: bool = True) -> List[Dict]:
        """Pesquisa playlists no YouTube - NOTA: yt-dlp não suporta pesquisa de playlists diretamente"""
        logger.warning("⚠️ Pesquisa de playlists não disponível via yt-dlp")
        logger.info("💡 Use --url com URL direta da playlist para extrair vídeos")
        logger.info("   Exemplo: python scraper_youtube.py --url 'https://www.youtube.com/playlist?list=...'")
        return []

    def _is_playlist_separated(self, playlist_url: str) -> bool:
        """Verifica se playlist tem músicas separadas (não arquivo único)"""
        # Por padrão, considera todas as playlists como separadas
        # O YouTube não tem playlists de arquivo único como outros sites
        return True

    def _generate_md5(self, text: str) -> str:
        """Gera hash MD5"""
        return hashlib.md5(text.encode()).hexdigest()

    def _sanitize(self, val):
        """Remove caracteres nulos"""
        if isinstance(val, str):
            return val.replace('\x00', '').replace('\\u0000', '')
        return val

    def _batch_upsert(self, table: str, records: List[Dict], conflict_col: str) -> int:
        """Faz upsert em lote no Supabase"""
        if not records:
            return 0

        total = 0
        for i in range(0, len(records), self.BATCH_SIZE):
            batch = records[i:i + self.BATCH_SIZE]
            try:
                self.supabase.table(table).upsert(batch, on_conflict=conflict_col).execute()
                total += len(batch)
            except Exception as e:
                logger.warning(f"⚠️ Erro no upsert em {table} ({len(batch)} registros): {e}")
                for record in batch:
                    try:
                        self.supabase.table(table).upsert(record, on_conflict=conflict_col).execute()
                        total += 1
                    except Exception:
                        pass

        return total

    def save_video_to_supabase(self, video: Dict) -> bool:
        """Salva metadados de um vídeo no Supabase"""
        video_id = self._generate_md5(video['video_id'])
        
        try:
            record = {
                'id': video_id,
                'video_id': video['video_id'],
                'title': self._sanitize(video['title']),
                'uploader': self._sanitize(video['uploader']),
                'uploader_id': self._sanitize(video['uploader_id']),
                'duration': video['duration'],
                'view_count': video['view_count'],
                'upload_date': self._sanitize(video['upload_date']),
                'description': self._sanitize(video['description']),
                'thumbnail': self._sanitize(video['thumbnail']),
                'url': self._sanitize(video['url']),
                'audio_url': self._sanitize(video['audio_url']) if video.get('audio_url') else None,
                'audio_format': self._sanitize(video['audio_format']) if video.get('audio_format') else None,
            }
            
            self.supabase.table('youtube_videos').upsert(record, on_conflict='id').execute()
            logger.info(f"✅ Vídeo salvo: {video['title'][:50]}")
            return True
        except Exception as e:
            logger.error(f"❌ Erro ao salvar vídeo: {e}")
            return False

    def scrape_video(self, url: str) -> bool:
        """Extrai e salva metadados de um vídeo"""
        logger.info(f"Extraindo vídeo: {url}")
        video_info = self._extract_video_info(url)
        
        if video_info:
            return self.save_video_to_supabase(video_info)
        return False

    def scrape_playlist(self, url: str) -> int:
        """Extrai e salva metadados de uma playlist"""
        logger.info(f"Extraindo playlist: {url}")
        videos = self._extract_playlist_info(url)
        
        saved_count = 0
        for video in videos:
            if self.save_video_to_supabase(video):
                saved_count += 1
            time.sleep(0.5)  # Rate limiting
        
        logger.info(f"✅ Playlist: {saved_count}/{len(videos)} vídeos salvos")
        return saved_count

    def run(self, url: str = None, search: str = None, search_type: str = 'music', limit: int = 10, 
            action: str = None, output_path: str = None):
        """Executa o scraper"""
        logger.info("🚀 Iniciando scraper YouTube")
        
        if search:
            if search_type == 'music':
                results = self.search_music(search, limit)
                logger.info(f"🎵 {len(results)} músicas encontradas para '{search}'")
                for i, result in enumerate(results, 1):
                    logger.info(f"  {i}. {result['title'][:50]} - {result['uploader']}")
                    logger.info(f"     URL: {result['url']}")
                    
                    # Se ação especificada, executa no primeiro resultado
                    if action and i == 1:
                        self._execute_action(result['url'], action, output_path)
            elif search_type == 'playlist':
                results = self.search_playlists(search, limit, separated_only=True)
                logger.info(f"📋 {len(results)} playlists separadas encontradas para '{search}'")
                for i, result in enumerate(results, 1):
                    logger.info(f"  {i}. {result['title'][:50]} - {result['video_count']} vídeos")
                    logger.info(f"     URL: {result['url']}")
        elif url:
            if 'playlist' in url.lower():
                self.scrape_playlist(url)
            else:
                self.scrape_video(url)
                
            # Se ação especificada, executa
            if action:
                self._execute_action(url, action, output_path)
        
        logger.info("✅ Scraper finalizado!")

    def _execute_action(self, url: str, action: str, output_path: str = None):
        """Executa ação (stream/download/play) em um vídeo"""
        if action == 'stream':
            audio_url = self.get_audio_stream_url(url)
            if audio_url:
                logger.info(f"🎵 URL de stream: {audio_url}")
            else:
                logger.error("❌ Não foi possível obter URL de stream")
        elif action == 'download':
            filename = self.download_audio(url, output_path)
            if filename:
                logger.info(f"✅ Arquivo salvo em: {filename}")
        elif action == 'play':
            if self.play_audio(url):
                logger.info("✅ Áudio iniciado")
            else:
                logger.error("❌ Não foi possível tocar áudio")

    def interactive_mode(self):
        """Modo interativo para pesquisar e escolher músicas"""
        print("\n" + "="*60)
        print("🎵 YouTube Scraper - Modo Interativo")
        print("="*60)
        
        while True:
            print("\nOpções:")
            print("1. Pesquisar músicas")
            print("2. Sair")
            
            choice = input("\nEscolha uma opção (1-2): ").strip()
            
            if choice == '1':
                query = input("Digite o nome da música ou artista: ").strip()
                if not query:
                    print("❌ Termo de pesquisa vazio")
                    continue
                
                limit = input("Quantos resultados? (padrão: 10): ").strip()
                try:
                    limit = int(limit) if limit else 10
                except ValueError:
                    limit = 10
                
                results = self.search_music(query, limit)
                
                if not results:
                    print("❌ Nenhum resultado encontrado")
                    continue
                
                print(f"\n🎵 {len(results)} resultados encontrados para '{query}':")
                print("-" * 60)
                
                for i, result in enumerate(results, 1):
                    duration_min = result['duration'] // 60
                    duration_sec = result['duration'] % 60
                    print(f"{i}. {result['title'][:50]}")
                    print(f"   Artista: {result['uploader']}")
                    print(f"   Duração: {duration_min}:{duration_sec:02d}")
                    print(f"   Visualizações: {result['view_count']:,}")
                    print("-" * 60)
                
                while True:
                    selection = input(f"\nEscolha uma música (1-{len(results)}) ou 'v' para voltar: ").strip()
                    
                    if selection.lower() == 'v':
                        break
                    
                    try:
                        index = int(selection) - 1
                        if 0 <= index < len(results):
                            selected = results[index]
                            print(f"\n🎵 Selecionado: {selected['title']}")
                            print(f"   Artista: {selected['uploader']}")
                            
                            print("\nAções:")
                            print("1. Obter URL de stream")
                            print("2. Baixar áudio")
                            print("3. Tocar áudio")
                            print("4. Voltar")
                            
                            action_choice = input("Escolha uma ação (1-4): ").strip()
                            
                            if action_choice == '1':
                                audio_url = self.get_audio_stream_url(selected['url'])
                                if audio_url:
                                    print(f"\n🎵 URL de stream: {audio_url}")
                                else:
                                    print("❌ Não foi possível obter URL de stream")
                            
                            elif action_choice == '2':
                                output_path = input("Caminho de saída (padrão: downloads): ").strip()
                                output_path = output_path if output_path else "downloads"
                                filename = self.download_audio(selected['url'], output_path)
                                if filename:
                                    print(f"✅ Arquivo salvo em: {filename}")
                                else:
                                    print("❌ Erro ao baixar áudio")
                            
                            elif action_choice == '3':
                                if self.play_audio(selected['url']):
                                    print("✅ Áudio iniciado")
                                else:
                                    print("❌ Não foi possível tocar áudio")
                            
                            elif action_choice == '4':
                                continue
                            
                            else:
                                print("❌ Opção inválida")
                        else:
                            print("❌ Seleção inválida")
                    except ValueError:
                        print("❌ Entrada inválida")
            
            elif choice == '2':
                print("\n👋 Saindo...")
                break
            
            else:
                print("❌ Opção inválida")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Scraper YouTube')
    parser.add_argument('--url', type=str, help='URL do vídeo ou playlist')
    parser.add_argument('--search', type=str, help='Termo de pesquisa')
    parser.add_argument('--type', type=str, default='music', choices=['music', 'playlist'], help='Tipo de pesquisa: music ou playlist')
    parser.add_argument('--limit', type=int, default=10, help='Limite de resultados')
    parser.add_argument('--action', type=str, choices=['stream', 'download', 'play'], help='Ação: stream (obter URL), download (baixar), play (tocar)')
    parser.add_argument('--output', type=str, help='Caminho de saída para download (padrão: downloads/)')
    parser.add_argument('--interactive', action='store_true', help='Modo interativo para pesquisar e escolher músicas')
    
    args = parser.parse_args()
    
    scraper = YouTubeScraper()
    
    if args.interactive:
        scraper.interactive_mode()
    else:
        scraper.run(url=args.url, search=args.search, search_type=args.type, limit=args.limit, 
                    action=args.action, output_path=args.output)
