import os
import re
import uuid
import json
import logging
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from supabase import create_client, Client
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class JamendoScraper:
    """Scraper para extrair dados do Jamendo"""

    BASE_URL = "https://www.jamendo.com"
    JAMENDO_API_BASE = "https://api.jamendo.com/v3.0"
    
    # URLs alvo
    URLS = [
        "/start",
        "/explore/playlists",
        "/explore/latestreleases",
        "/explore",
        "/blog"
    ]

    def __init__(self):
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_KEY')
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")

        self.jamendo_client_id = os.getenv('JAMENDO_CLIENT_ID')
        if not self.jamendo_client_id:
            logger.warning("JAMENDO_CLIENT_ID não definido. O site do Jamendo carrega dados via JavaScript e a extração HTML pode falhar.")

        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })

        # Track processed items to avoid duplicates
        self.processed_music_ids = set()
        self.processed_artist_slugs = set()
        self.processed_genre_names = set()
        self.processed_playlist_ids = set()
        self.processed_blog_ids = set()

    def _clean_text(self, text: str) -> str:
        if not text:
            return ''
        return ' '.join(text.strip().split())

    def _generate_id(self, prefix: str = '', max_length: int = 32) -> str:
        """Gera um ID único com tamanho máximo especificado"""
        import hashlib
        unique_str = f"{prefix}{uuid.uuid4().hex}"
        hash_obj = hashlib.md5(unique_str.encode())
        hash_hex = hash_obj.hexdigest()
        return hash_hex[:max_length]

    def _extract_duration(self, text: str) -> Optional[str]:
        """Extrai duração no formato MM:SS"""
        if not text:
            return None
        match = re.search(r'(\d+:\d+)', text)
        return match.group(1) if match else None

    def _parse_json_ld(self, soup: BeautifulSoup) -> List[Dict]:
        """Extrai dados do JSON-LD estruturado na página"""
        items = []
        
        script_tags = soup.find_all('script', type='application/ld+json')
        
        for script_tag in script_tags:
            if not script_tag.string:
                continue
                
            try:
                data = json.loads(script_tag.string)
                
                # Se for um array
                if isinstance(data, list):
                    for item in data:
                        items.extend(self._process_json_item(item))
                # Se for um objeto único
                elif isinstance(data, dict):
                    items.extend(self._process_json_item(data))
                    
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Erro ao parsear JSON-LD: {e}")
                continue
        
        return items

    def _process_json_item(self, item: Dict) -> List[Dict]:
        """Processa um item JSON-LD"""
        results = []
        
        if not isinstance(item, dict):
            return results
        
        item_type = item.get('@type', '')
        
        # Processa MusicPlaylist
        if item_type == 'MusicPlaylist':
            item_list = item.get('itemListElement', [])
            for entry in item_list:
                try:
                    music_item = entry.get('item', {})
                    if music_item.get('@type') == 'MusicRecording':
                        result = self._extract_music_from_json(music_item)
                        if result:
                            results.append(result)
                except Exception as e:
                    logger.warning(f"Erro ao processar item da playlist: {e}")
        
        # Processa MusicRecording individual
        elif item_type == 'MusicRecording':
            result = self._extract_music_from_json(item)
            if result:
                results.append(result)
        
        # Processa BlogPosting
        elif item_type == 'BlogPosting':
            result = self._extract_blog_from_json(item)
            if result:
                results.append(result)
        
        # Processa ListItem com MusicRecording
        elif item_type == 'ListItem':
            music_item = item.get('item', {})
            if music_item.get('@type') == 'MusicRecording':
                result = self._extract_music_from_json(music_item)
                if result:
                    results.append(result)
        
        return results

    def _extract_music_from_json(self, data: Dict) -> Optional[Dict]:
        """Extrai dados de música do JSON"""
        try:
            # Tenta obter o título
            title = data.get('name', 'Unknown Song')
            
            # Tenta obter o artista
            artist_info = data.get('byArtist', {})
            if isinstance(artist_info, dict):
                artist_name = artist_info.get('name', 'Unknown Artist')
            elif isinstance(artist_info, list):
                artist_name = ', '.join([a.get('name', 'Unknown Artist') for a in artist_info if isinstance(a, dict)])
            else:
                artist_name = 'Unknown Artist'
            
            # URL da capa
            cover_url = data.get('image')
            if isinstance(cover_url, list):
                cover_url = cover_url[0] if cover_url else None
            
            # URL da música
            music_url = data.get('url')
            
            # Duração
            duration = data.get('duration')
            if duration:
                # Formata duração se necessário
                if duration.startswith('PT'):
                    duration = duration.replace('PT', '').replace('M', ':').replace('S', '')
                    if ':' in duration:
                        duration = duration.split(':')[1] if len(duration.split(':')) > 1 else duration
            
            # Descrição
            description = data.get('description')
            
            return {
                'title': title,
                'artist_name': artist_name,
                'cover_url': cover_url,
                'music_url': music_url,
                'duration': duration,
                'description': description,
                'source': 'json-ld'
            }
            
        except Exception as e:
            logger.warning(f"Erro ao extrair música do JSON: {e}")
            return None

    def _extract_blog_from_json(self, data: Dict) -> Optional[Dict]:
        """Extrai dados de blog post do JSON"""
        try:
            title = data.get('headline', data.get('name', 'Untitled Post'))
            description = data.get('description', '')
            url = data.get('url')
            date_published = data.get('datePublished')
            author = data.get('author', {})
            author_name = author.get('name', 'Unknown Author') if isinstance(author, dict) else 'Unknown Author'
            image = data.get('image')
            if isinstance(image, list):
                image = image[0] if image else None
            
            return {
                'title': title,
                'description': description,
                'url': url,
                'date_published': date_published,
                'author_name': author_name,
                'image_url': image,
                'source': 'json-ld'
            }
            
        except Exception as e:
            logger.warning(f"Erro ao extrair blog post do JSON: {e}")
            return None

    def _parse_html_music_tracks(self, soup: BeautifulSoup) -> List[Dict]:
        """Extrai tracks de música do HTML"""
        tracks = []
        
        # Procura por elementos que contenham músicas
        track_selectors = [
            '.track-card',
            '.music-card',
            '.release-card',
            '.album-card',
            '.playlist-track',
            '.track-item',
            '[data-testid="track"]',
            '.song-item',
            '.music-item'
        ]
        
        for selector in track_selectors:
            elements = soup.select(selector)
            if elements:
                logger.info(f"Encontrados {len(elements)} elementos com selector '{selector}'")
                for elem in elements:
                    try:
                        track = self._extract_track_from_element(elem)
                        if track:
                            tracks.append(track)
                    except Exception as e:
                        logger.warning(f"Erro ao extrair track: {e}")
        
        return tracks

    def _extract_track_from_element(self, elem: BeautifulSoup) -> Optional[Dict]:
        """Extrai dados de uma track de um elemento HTML"""
        try:
            # Título
            title_elem = elem.select_one('.track-title, .song-title, .name, .title, h4, h3')
            title = self._clean_text(title_elem.get_text()) if title_elem else 'Unknown Track'
            
            # Artista
            artist_elem = elem.select_one('.artist-name, .artist, .by-artist, .creator')
            artist_name = self._clean_text(artist_elem.get_text()) if artist_elem else 'Unknown Artist'
            
            # Capa
            img_elem = elem.select_one('img')
            cover_url = None
            if img_elem:
                cover_url = img_elem.get('src') or img_elem.get('data-src')
                if cover_url and not cover_url.startswith('http'):
                    cover_url = urljoin(self.BASE_URL, cover_url)
            
            # URL
            link_elem = elem.select_one('a')
            track_url = None
            if link_elem:
                href = link_elem.get('href')
                if href:
                    track_url = urljoin(self.BASE_URL, href)
            
            # Duração
            duration_elem = elem.select_one('.duration, .length, .time')
            duration = None
            if duration_elem:
                duration = self._extract_duration(duration_elem.get_text())
            
            return {
                'title': title,
                'artist_name': artist_name,
                'cover_url': cover_url,
                'music_url': track_url,
                'duration': duration,
                'source': 'html'
            }
            
        except Exception as e:
            logger.warning(f"Erro ao extrair track do elemento: {e}")
            return None

    def _parse_html_playlists(self, soup: BeautifulSoup) -> List[Dict]:
        """Extrai playlists do HTML"""
        playlists = []
        
        playlist_selectors = [
            '.playlist-card',
            '.playlist-item',
            '[data-testid="playlist"]',
            '.playlist'
        ]
        
        for selector in playlist_selectors:
            elements = soup.select(selector)
            if elements:
                logger.info(f"Encontrados {len(elements)} elementos de playlist com selector '{selector}'")
                for elem in elements:
                    try:
                        playlist = self._extract_playlist_from_element(elem)
                        if playlist:
                            playlists.append(playlist)
                    except Exception as e:
                        logger.warning(f"Erro ao extrair playlist: {e}")
        
        return playlists

    def _extract_playlist_from_element(self, elem: BeautifulSoup) -> Optional[Dict]:
        """Extrai dados de uma playlist de um elemento HTML"""
        try:
            # Nome
            name_elem = elem.select_one('.playlist-name, .title, .name, h4, h3')
            name = self._clean_text(name_elem.get_text()) if name_elem else 'Unknown Playlist'
            
            # Descrição
            desc_elem = elem.select_one('.description, .desc, .playlist-description')
            description = self._clean_text(desc_elem.get_text()) if desc_elem else ''
            
            # Imagem
            img_elem = elem.select_one('img')
            image_url = None
            if img_elem:
                image_url = img_elem.get('src') or img_elem.get('data-src')
                if image_url and not image_url.startswith('http'):
                    image_url = urljoin(self.BASE_URL, image_url)
            
            # URL
            link_elem = elem.select_one('a')
            url = None
            if link_elem:
                href = link_elem.get('href')
                if href:
                    url = urljoin(self.BASE_URL, href)
            
            # Número de músicas
            tracks_elem = elem.select_one('.track-count, .count, .tracks')
            track_count = None
            if tracks_elem:
                track_text = self._clean_text(tracks_elem.get_text())
                match = re.search(r'\d+', track_text)
                if match:
                    track_count = int(match.group())
            
            return {
                'name': name,
                'description': description,
                'image_url': image_url,
                'url': url,
                'track_count': track_count,
                'source': 'html'
            }
            
        except Exception as e:
            logger.warning(f"Erro ao extrair playlist do elemento: {e}")
            return None

    def _parse_html_blog_posts(self, soup: BeautifulSoup) -> List[Dict]:
        """Extrai posts do blog do HTML"""
        posts = []
        
        blog_selectors = [
            '.blog-post',
            '.post-card',
            '.article-card',
            '.post-item',
            '.blog-item',
            'article'
        ]
        
        for selector in blog_selectors:
            elements = soup.select(selector)
            if elements:
                logger.info(f"Encontrados {len(elements)} elementos de blog com selector '{selector}'")
                for elem in elements:
                    try:
                        post = self._extract_blog_from_element(elem)
                        if post:
                            posts.append(post)
                    except Exception as e:
                        logger.warning(f"Erro ao extrair blog post: {e}")
        
        return posts

    def _jamendo_api_get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        if not self.jamendo_client_id:
            return None

        params = params.copy() if params else {}
        params.update({
            'client_id': self.jamendo_client_id,
            'format': 'json'
        })

        try:
            response = self.session.get(f"{self.JAMENDO_API_BASE}/{endpoint}", params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            if data.get('headers', {}).get('status') != 'ok':
                logger.warning(f"Jamendo API returned status failed: {data.get('headers', {}).get('error_message')}")
                return None
            return data
        except requests.RequestException as e:
            logger.error(f"Erro na requisição à Jamendo API: {e}")
            return None
        except ValueError as e:
            logger.error(f"Erro ao decodificar JSON da Jamendo API: {e}")
            return None

    def _format_api_duration(self, duration_seconds: Optional[int]) -> Optional[str]:
        if duration_seconds is None:
            return None
        try:
            duration_seconds = int(duration_seconds)
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            return f"{minutes}:{seconds:02d}"
        except (ValueError, TypeError):
            return None

    def scrape_api_tracks(self, limit: int = 20) -> List[Dict]:
        if not self.jamendo_client_id:
            return []

        logger.info(f"Extraindo músicas via Jamendo API (limit={limit})")
        data = self._jamendo_api_get('tracks', {
            'limit': limit,
            'order': 'popularity_total',
            'include': 'musicinfo',
            'imagesize': 200
        })
        if not data:
            return []

        musics = []
        for item in data.get('results', []):
            musics.append({
                'title': item.get('name'),
                'artist_name': item.get('artist_name'),
                'cover_url': item.get('album_image'),
                'music_url': item.get('shareurl'),
                'duration': self._format_api_duration(item.get('duration')),
                'album': item.get('album_name'),
                'release_year': item.get('releasedate', '')[:4] if item.get('releasedate') else None,
                'genre': item.get('musicinfo', {}).get('genres', [{}])[0].get('name') if item.get('musicinfo') else None,
                'source': 'api'
            })

        logger.info(f"Jamendo API: {len(musics)} músicas extraídas")
        return musics

    def scrape_api_playlists(self, limit: int = 20) -> List[Dict]:
        if not self.jamendo_client_id:
            return []

        logger.info(f"Extraindo playlists via Jamendo API (limit={limit})")
        data = self._jamendo_api_get('playlists', {
            'limit': limit,
            'order': 'createdate_desc',
            'include': 'tracks'
        })
        if not data:
            return []

        playlists = []
        for item in data.get('results', []):
            playlists.append({
                'name': item.get('name'),
                'description': item.get('description'),
                'image_url': item.get('image'),
                'url': item.get('shareurl'),
                'track_count': item.get('track_count'),
                'source': 'api'
            })

        logger.info(f"Jamendo API: {len(playlists)} playlists extraídas")
        return playlists

    def scrape_api_data(self) -> Dict:
        data = {
            'musics': [],
            'playlists': [],
            'blog_posts': [],
            'metadata': {}
        }

        data['musics'] = self.scrape_api_tracks(limit=50)
        data['playlists'] = self.scrape_api_playlists(limit=25)
        return data

    def _extract_blog_from_element(self, elem: BeautifulSoup) -> Optional[Dict]:
        """Extrai dados de um blog post de um elemento HTML"""
        try:
            # Título
            title_elem = elem.select_one('h1, h2, h3, .title, .post-title, .headline')
            title = self._clean_text(title_elem.get_text()) if title_elem else 'Untitled Post'
            
            # Descrição/Resumo
            desc_elem = elem.select_one('.description, .excerpt, .summary, .post-description, p')
            description = self._clean_text(desc_elem.get_text()) if desc_elem else ''
            
            # Imagem
            img_elem = elem.select_one('img')
            image_url = None
            if img_elem:
                image_url = img_elem.get('src') or img_elem.get('data-src')
                if image_url and not image_url.startswith('http'):
                    image_url = urljoin(self.BASE_URL, image_url)
            
            # URL
            link_elem = elem.select_one('a')
            url = None
            if link_elem:
                href = link_elem.get('href')
                if href:
                    url = urljoin(self.BASE_URL, href)
            
            # Autor
            author_elem = elem.select_one('.author, .byline, .writer, .post-author')
            author = self._clean_text(author_elem.get_text()) if author_elem else 'Unknown Author'
            
            # Data
            date_elem = elem.select_one('.date, .published, .post-date, time')
            date = None
            if date_elem:
                date = self._clean_text(date_elem.get_text())
                # Tenta extrair atributo datetime
                if date_elem.get('datetime'):
                    date = date_elem.get('datetime')
            
            return {
                'title': title,
                'description': description,
                'image_url': image_url,
                'url': url,
                'author': author,
                'date': date,
                'source': 'html'
            }
            
        except Exception as e:
            logger.warning(f"Erro ao extrair blog post do elemento: {e}")
            return None

    def scrape_page(self, url_path: str) -> Dict:
        """Extrai dados de uma página específica"""
        full_url = urljoin(self.BASE_URL, url_path)
        logger.info(f"Extraindo dados de: {full_url}")
        
        result = {
            'url': full_url,
            'musics': [],
            'playlists': [],
            'blog_posts': [],
            'metadata': {}
        }
        
        try:
            response = self.session.get(full_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extrai JSON-LD
            json_items = self._parse_json_ld(soup)
            for item in json_items:
                if 'artist_name' in item:  # É uma música
                    result['musics'].append(item)
                elif 'author_name' in item:  # É um blog post
                    result['blog_posts'].append(item)
                elif 'author' in item:  # Blog post do HTML
                    result['blog_posts'].append(item)
            
            # Extrai do HTML
            result['musics'].extend(self._parse_html_music_tracks(soup))
            result['playlists'].extend(self._parse_html_playlists(soup))
            result['blog_posts'].extend(self._parse_html_blog_posts(soup))
            
            # Extrai metadados da página
            meta_tags = soup.find_all('meta')
            for meta in meta_tags:
                name = meta.get('name') or meta.get('property')
                content = meta.get('content')
                if name and content:
                    result['metadata'][name] = content
            
            # Título da página
            title_tag = soup.find('title')
            if title_tag:
                result['metadata']['title'] = self._clean_text(title_tag.get_text())
            
            logger.info(f"✅ Página extraída: {len(result['musics'])} músicas, {len(result['playlists'])} playlists, {len(result['blog_posts'])} posts")
            
        except requests.RequestException as e:
            logger.error(f"Erro na requisição HTTP para {full_url}: {e}")
        except Exception as e:
            logger.error(f"Erro ao extrair dados de {full_url}: {e}")
        
        return result

    def scrape_all_pages(self) -> Dict:
        """Extrai dados de todas as páginas"""
        all_results = {
            'musics': [],
            'playlists': [],
            'blog_posts': [],
            'metadata': {}
        }
        
        for url_path in self.URLS:
            result = self.scrape_page(url_path)
            
            # Adiciona os resultados
            all_results['musics'].extend(result['musics'])
            all_results['playlists'].extend(result['playlists'])
            all_results['blog_posts'].extend(result['blog_posts'])
            all_results['metadata'][url_path] = result['metadata']
        
        # Remove duplicatas baseado no título + artista (para músicas)
        unique_musics = []
        seen = set()
        for music in all_results['musics']:
            key = f"{music.get('title', '')}|{music.get('artist_name', '')}"
            if key not in seen:
                seen.add(key)
                unique_musics.append(music)
        all_results['musics'] = unique_musics
        
        # Remove duplicatas de playlists baseado no nome
        unique_playlists = []
        seen = set()
        for playlist in all_results['playlists']:
            key = playlist.get('name', '')
            if key not in seen:
                seen.add(key)
                unique_playlists.append(playlist)
        all_results['playlists'] = unique_playlists
        
        # Remove duplicatas de blog posts baseado no título
        unique_posts = []
        seen = set()
        for post in all_results['blog_posts']:
            key = post.get('title', '')
            if key not in seen:
                seen.add(key)
                unique_posts.append(post)
        all_results['blog_posts'] = unique_posts
        
        logger.info(f"📊 Totais: {len(all_results['musics'])} músicas, {len(all_results['playlists'])} playlists, {len(all_results['blog_posts'])} posts")
        
        return all_results

    def save_to_supabase(self, data: Dict) -> int:
        """Salva os dados no Supabase"""
        saved_count = 0
        
        # Salva músicas
        for music in data['musics']:
            try:
                music_id = self._generate_id('mus_', 32)
                
                if music_id not in self.processed_music_ids:
                    # Salva artista se necessário
                    artist_id = None
                    artist_slug = music.get('artist_name', '').lower().replace(' ', '-')
                    artist_slug = re.sub(r'[^a-z0-9-]', '', artist_slug)
                    
                    if artist_slug and artist_slug not in self.processed_artist_slugs:
                        try:
                            existing = self.supabase.table('artists').select('id').eq('slug', artist_slug).execute()
                            if not existing.data:
                                artist_id = self._generate_id('art_', 16)
                                self.supabase.table('artists').insert({
                                    'id': artist_id,
                                    'name': music.get('artist_name', 'Unknown Artist'),
                                    'slug': artist_slug,
                                    'genre': 'Música'
                                }).execute()
                                self.processed_artist_slugs.add(artist_slug)
                                logger.info(f"👤 Artista salvo: {music.get('artist_name')}")
                            else:
                                artist_id = existing.data[0]['id']
                        except Exception as e:
                            logger.warning(f"Erro ao salvar artista: {e}")
                    
                    # Salva música
                    try:
                        self.supabase.table('musics').insert({
                            'id': music_id,
                            'title': music.get('title', 'Unknown Track'),
                            'artist_id': artist_id,
                            'artist_name': music.get('artist_name', 'Unknown Artist'),
                            'artist_slug': artist_slug,
                            'album': None,
                            'release_year': None,
                            'genre': None,
                            'plays': 0,
                            'cover_url': music.get('cover_url'),
                            'mp3_url': music.get('music_url'),
                            'palcomp3_url': None,
                            'duration': music.get('duration')
                        }).execute()
                        self.processed_music_ids.add(music_id)
                        saved_count += 1
                        logger.info(f"✅ Música salva: {music.get('title')}")
                    except Exception as e:
                        logger.warning(f"Erro ao salvar música: {e}")
                        
            except Exception as e:
                logger.error(f"Erro ao processar música: {e}")
        
        # Salva playlists
        for playlist in data['playlists']:
            try:
                playlist_id = self._generate_id('pl_', 32)
                
                if playlist_id not in self.processed_playlist_ids:
                    self.supabase.table('playlists').insert({
                        'id': playlist_id,
                        'name': playlist.get('name', 'Unknown Playlist'),
                        'description': playlist.get('description', ''),
                        'image_url': playlist.get('image_url'),
                        'track_count': playlist.get('track_count', 0),
                        'url': playlist.get('url')
                    }).execute()
                    self.processed_playlist_ids.add(playlist_id)
                    saved_count += 1
                    logger.info(f"📋 Playlist salva: {playlist.get('name')}")
            except Exception as e:
                logger.warning(f"Erro ao salvar playlist: {e}")
        
        # Salva blog posts
        for post in data['blog_posts']:
            try:
                post_id = self._generate_id('blog_', 32)
                
                if post_id not in self.processed_blog_ids:
                    self.supabase.table('blog_posts').insert({
                        'id': post_id,
                        'title': post.get('title', 'Untitled Post'),
                        'description': post.get('description', ''),
                        'image_url': post.get('image_url'),
                        'url': post.get('url'),
                        'author': post.get('author') or post.get('author_name', 'Unknown Author'),
                        'date': post.get('date') or post.get('date_published')
                    }).execute()
                    self.processed_blog_ids.add(post_id)
                    saved_count += 1
                    logger.info(f"📝 Blog post salvo: {post.get('title')}")
            except Exception as e:
                logger.warning(f"Erro ao salvar blog post: {e}")
        
        return saved_count

    def run(self):
        """Executa o scraper completo"""
        logger.info("🚀 Iniciando scraper do Jamendo")
        
        data = self.scrape_all_pages()
        if not data['musics'] and not data['playlists'] and not data['blog_posts']:
            logger.warning("Nenhum dado HTML encontrado. Tentando Jamendo API se JAMENDO_CLIENT_ID estiver definido...")
            api_data = self.scrape_api_data()
            data['musics'] = api_data.get('musics', [])
            data['playlists'] = api_data.get('playlists', [])
            data['metadata'].update(api_data.get('metadata', {}))

        # Salva no Supabase
        if data['musics'] or data['playlists'] or data['blog_posts']:
            saved = self.save_to_supabase(data)
            logger.info(f"✅ {saved} itens salvos com sucesso!")
        else:
            logger.warning("⚠️ Nenhum dado encontrado para salvar")
        
        logger.info("🏁 Scraper finalizado!")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    scraper = JamendoScraper()
    scraper.run()