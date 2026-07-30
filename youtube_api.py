"""
YouTube API REST - API para consumo por app Dart
Endpoints:
- GET /search?q=termo&limit=10 - Pesquisar músicas
- GET /stream?url=... - Obter URL de stream
- GET /download?url=... - Baixar áudio (retorna arquivo)
"""

import os
import logging
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Habilita CORS para consumo pelo app Dart

class YouTubeAPI:
    """API para operações do YouTube"""
    
    def __init__(self):
        self.download_dir = 'temp_downloads'
        os.makedirs(self.download_dir, exist_ok=True)
        
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
            'extract_flat': False,
            'quiet': True,
            'no_warnings': True,
        })
        
        # Adiciona cookies se arquivo existir
        cookie_file = os.getenv('YOUTUBE_COOKIES_FILE', 'cookies.txt')
        if os.path.exists(cookie_file):
            opts['cookiefile'] = cookie_file
            logger.info(f"Usando cookies de: {cookie_file}")
        
        return opts
    
    def search_music(self, query: str, limit: int = 10):
        """Pesquisa músicas no YouTube"""
        search_query = f"ytsearch{limit}:{query}"
        ydl_opts = self._get_ydl_opts()
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                
                results = []
                if 'entries' in info:
                    for entry in info['entries']:
                        if entry and entry.get('id'):
                            results.append({
                                'video_id': entry.get('id'),
                                'title': entry.get('title', ''),
                                'uploader': entry.get('uploader', ''),
                                'duration': entry.get('duration', 0),
                                'view_count': entry.get('view_count', 0),
                                'url': entry.get('webpage_url', ''),
                                'thumbnail': entry.get('thumbnail', ''),
                            })
                
                return {'success': True, 'results': results}
        except Exception as e:
            logger.error(f"Erro ao pesquisar: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_stream_url(self, url: str):
        """Obtém URL de stream de áudio"""
        ydl_opts = self._get_ydl_opts({'format': 'bestaudio/best'})
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get('formats', [])
                audio_formats = [f for f in formats if f.get('acodec') != 'none']
                
                if audio_formats:
                    return {'success': True, 'stream_url': audio_formats[0].get('url', '')}
                
                return {'success': False, 'error': 'Nenhum formato de áudio encontrado'}
        except Exception as e:
            logger.error(f"Erro ao obter stream: {e}")
            return {'success': False, 'error': str(e)}
    
    def download_audio(self, url: str):
        """Baixa áudio e retorna o arquivo"""
        ydl_opts = self._get_ydl_opts({
            'format': 'bestaudio/best',
            'outtmpl': f'{self.download_dir}/%(id)s.%(ext)s',
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
                
                if os.path.exists(filename):
                    return {'success': True, 'filename': filename}
                else:
                    return {'success': False, 'error': 'Arquivo não encontrado após download'}
        except Exception as e:
            logger.error(f"Erro ao baixar: {e}")
            return {'success': False, 'error': str(e)}

youtube_api = YouTubeAPI()

@app.route('/search', methods=['GET'])
def search():
    """Endpoint para pesquisar músicas"""
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 10))
    
    if not query:
        return jsonify({'success': False, 'error': 'Query parameter required'}), 400
    
    result = youtube_api.search_music(query, limit)
    return jsonify(result)

@app.route('/stream', methods=['GET'])
def stream():
    """Endpoint para obter URL de stream"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL parameter required'}), 400
    
    result = youtube_api.get_stream_url(url)
    return jsonify(result)

@app.route('/download', methods=['GET'])
def download():
    """Endpoint para baixar áudio"""
    url = request.args.get('url', '')
    
    if not url:
        return jsonify({'success': False, 'error': 'URL parameter required'}), 400
    
    result = youtube_api.download_audio(url)
    
    if result['success']:
        try:
            return send_file(result['filename'], as_attachment=True, mimetype='audio/mpeg')
        except Exception as e:
            logger.error(f"Erro ao enviar arquivo: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    else:
        return jsonify(result), 400

@app.route('/health', methods=['GET'])
def health():
    """Endpoint de health check"""
    return jsonify({'status': 'healthy', 'service': 'YouTube API'})

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
