import os
import re
import uuid
import json
import logging
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from supabase import create_client, Client
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RadioAOVivoScraper:
    """Scraper que extrai as músicas mais tocadas do Radio Ao Vivo"""

    BASE_URL = "https://www.radio-ao-vivo.com"
    TOP_SONGS_URL = f"{BASE_URL}/mais-tocadas"

    def __init__(self):
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_KEY')
        if self.supabase_url and self.supabase_key:
            self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
        else:
            self.supabase = None
            logger.warning("SUPABASE_URL/SUPABASE_KEY não configurados. Extração funcionará, mas os resultados não serão salvos no Supabase.")

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        })

        # Track processed items to avoid duplicates
        self.processed_music_ids = set()
        self.processed_artist_slugs = set()
        self.processed_genre_names = set()
        self.processed_playlist_ids = set()

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

    def _extract_plays(self, text: str) -> int:
        if not text:
            return 0
        cleaned = re.sub(r'[.,\s]', '', text)
        match = re.search(r'\d+', cleaned)
        return int(match.group()) if match else 0

    def _extract_duration(self, text: str) -> Optional[str]:
        """Extrai duração no formato MM:SS"""
        if not text:
            return None
        match = re.search(r'(\d+:\d+)', text)
        return match.group(1) if match else None

    def _parse_json_ld(self, soup: BeautifulSoup) -> List[Dict]:
        """Extrai dados do JSON-LD estruturado na página"""
        musics = []
        
        script_tag = soup.find('script', type='application/ld+json')
        if not script_tag:
            return musics
        
        try:
            data = json.loads(script_tag.string)
            
            # O JSON-LD pode ser um array de objetos ou um único objeto
            graph = data
            if isinstance(data, dict) and '@graph' in data:
                graph = data['@graph']
            
            for item in graph:
                if isinstance(item, dict) and item.get('@type') == 'MusicPlaylist':
                    item_list = item.get('itemListElement', [])
                    for entry in item_list:
                        try:
                            position = entry.get('position', 0)
                            recording = entry.get('item', {})
                            
                            title = recording.get('name', 'Unknown Song')
                            
                            artist_info = recording.get('byArtist', {})
                            artist_name = artist_info.get('name', 'Unknown Artist')
                            
                            cover_url = recording.get('image')
                            apple_music_url = recording.get('url')
                            
                            musics.append({
                                'position': position,
                                'title': title,
                                'artist_name': artist_name,
                                'cover_url': cover_url,
                                'apple_music_url': apple_music_url,
                            })
                        except Exception as e:
                            logger.warning(f"Erro ao processar entrada JSON-LD: {e}")
                            continue
                    
                    # Já encontrou a playlist, pode parar
                    break
                    
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Erro ao parsear JSON-LD: {e}")
        
        return musics

    def _parse_html_charts(self, soup: BeautifulSoup) -> List[Dict]:
        """Extrai dados dos elementos HTML .charts-item"""
        musics = []
        
        chart_items = soup.select('.charts-item')
        logger.info(f"Encontrados {len(chart_items)} elementos .charts-item no HTML")
        
        for item in chart_items:
            try:
                # Posição/rank
                rank_elem = item.select_one('[class*="rank"]')
                position = int(self._clean_text(rank_elem.get_text())) if rank_elem else 0
                
                # Título
                title_elem = item.select_one('[class*="title"]')
                title = self._clean_text(title_elem.get_text()) if title_elem else 'Unknown Song'
                
                # Artista
                artist_elem = item.select_one('[class*="artist"]')
                artist_name = self._clean_text(artist_elem.get_text()) if artist_elem else 'Unknown Artist'
                
                # Capa
                img = item.select_one('img')
                cover_url = None
                if img:
                    cover_url = img.get('src') or img.get('data-src')
                    if cover_url and not cover_url.startswith('http'):
                        cover_url = urljoin(self.BASE_URL, cover_url)
                
                # Link da faixa
                link_elem = item.select_one('a[href]')
                track_url = None
                if link_elem:
                    href = link_elem.get('href')
                    if href:
                        track_url = urljoin(self.BASE_URL, href)

                # Preview URL (data-preview-url no elemento .charts-item)
                preview_url = item.get('data-preview-url') or item.get('data-url')

                musics.append({
                    'position': position,
                    'title': title,
                    'artist_name': artist_name,
                    'cover_url': cover_url,
                    'preview_url': preview_url,
                    'track_url': track_url,
                    'source': 'html'
                })
            except Exception as e:
                logger.warning(f"Erro ao processar elemento charts-item: {e}")
                continue
        
        return musics

    def _discover_genre_urls(self) -> List[Dict]:
        """Descobre as URLs de gêneros disponíveis no site a partir da página principal de mais tocadas"""
        logger.info(f"Descobrindo URLs de gêneros em: {self.TOP_SONGS_URL}")
        genres = []
        soup = None
        
        try:
            response = self.session.get(self.TOP_SONGS_URL, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Procura por links que seguem o padrão das páginas de gênero
            pattern = re.compile(r'/mais-tocadas/musicas-mais-tocadas-de-')
            for a_tag in soup.find_all('a', href=pattern):
                href = a_tag.get('href', '')
                # Extrai o nome do gênero da URL (ex: "alternativo" de "musicas-mais-tocadas-de-alternativo")
                genre_match = re.search(r'musicas-mais-tocadas-de-(.+?)(?:/|$)', href)
                if genre_match:
                    genre_slug = genre_match.group(1)
                    genre_name = genre_slug.replace('-', ' ').title()
                    full_url = urljoin(self.BASE_URL, href)
                    if full_url not in [g['url'] for g in genres]:
                        genres.append({
                            'name': genre_name,
                            'slug': genre_slug,
                            'url': full_url
                        })
                        logger.info(f"🎯 Gênero encontrado: {genre_name} -> {full_url}")
            
            # Se não encontrou links, tenta procurar em elementos de select/option
            if not genres:
                for option in soup.select('select[name="genre"] option, .genre-filter option'):
                    value = option.get('value', '')
                    if value and 'musicas-mais-tocadas-de-' in value:
                        genre_match = re.search(r'musicas-mais-tocadas-de-(.+?)(?:/|$)', value)
                        if genre_match:
                            genre_slug = genre_match.group(1)
                            genre_name = genre_slug.replace('-', ' ').title()
                            full_url = urljoin(self.BASE_URL, value)
                            genres.append({
                                'name': genre_name,
                                'slug': genre_slug,
                                'url': full_url
                            })
                            logger.info(f"🎯 Gênero encontrado (option): {genre_name}")
            
            logger.info(f"Total de gêneros encontrados: {len(genres)}")
            if not genres:
                logger.warning("Nenhum gênero encontrado! Usando apenas a página principal.")
                
        except Exception as e:
            logger.error(f"Erro ao descobrir URLs de gêneros: {e}")
        
        # Também usa links de gênero diretos se a pattern padrão não encontrou nada
        if not genres and soup is not None:
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if href.startswith('/genero/') or '/genero/' in href:
                    genre_name = href.split('/genero/')[-1].replace('-', ' ').title()
                    full_url = urljoin(self.BASE_URL, href)
                    if full_url not in [g['url'] for g in genres]:
                        genres.append({
                            'name': genre_name,
                            'slug': genre_name.lower().replace(' ', '-'),
                            'url': full_url
                        })
            if genres:
                logger.info(f"🎯 Gêneros alternativos encontrados via /genero/: {len(genres)}")

        return genres

    def scrape_top_songs(self, limit: int = None, genre_url: str = None, genre_name: str = None) -> List[Dict]:
        """Extrai as músicas mais tocadas do site usando requests + BeautifulSoup"""
        url = genre_url or self.TOP_SONGS_URL
        logger.info(f"Iniciando extração das músicas mais tocadas de: {url}")
        
        try:
            # Faz a requisição HTTP
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Tenta extrair do JSON-LD primeiro (mais estruturado)
            json_ld_musics = self._parse_json_ld(soup)
            logger.info(f"JSON-LD: {len(json_ld_musics)} músicas encontradas")
            
            # Tenta extrair do HTML
            html_musics = self._parse_html_charts(soup)
            logger.info(f"HTML: {len(html_musics)} músicas encontradas")
            
            # Usa os dados do HTML como base, enriquecendo com JSON-LD quando disponível
            # O HTML tem mais informações (preview_url), o JSON-LD tem apple_music_url
            musics_by_pos = {}
            
            for m in html_musics:
                pos = m['position']
                musics_by_pos[pos] = m
            
            for m in json_ld_musics:
                pos = m['position']
                if pos in musics_by_pos:
                    # Enriquece com dados do JSON-LD que não estão no HTML
                    if not musics_by_pos[pos].get('apple_music_url') and m.get('apple_music_url'):
                        musics_by_pos[pos]['apple_music_url'] = m['apple_music_url']
                else:
                    musics_by_pos[pos] = m
            
            # Ordena por posição
            sorted_positions = sorted(musics_by_pos.keys())
            all_musics = [musics_by_pos[pos] for pos in sorted_positions]
            
            # Converte para o formato esperado pelo banco
            result = []
            for music in all_musics:
                music_id = self._generate_id('mus_', 32)
                artist_slug = music['artist_name'].lower().replace(' ', '-')
                artist_slug = re.sub(r'[^a-z0-9-]', '', artist_slug)
                
                if music_id not in self.processed_music_ids:
                    current_genre = genre_name or 'Pop'
                    music_data = {
                        'id': music_id,
                        'title': music['title'],
                        'artist_name': music['artist_name'],
                        'artist_slug': artist_slug,
                        'genre': current_genre,
                        'plays': 0,  # O site não mostra número de plays
                        'palcomp3_url': music.get('apple_music_url'),
                        'mp3_url': music.get('preview_url'),  # URL de preview do Apple Music
                        'cover_url': music.get('cover_url'),
                        'album': None,
                        'release_year': None,
                        'duration': None,
                        'position': music['position']
                    }
                    
                    result.append(music_data)
                    self.processed_music_ids.add(music_id)
                    
                    logger.info(f"🎵 #{music['position']}: {music['title']} - {music['artist_name']}")
                    
                    if limit and len(result) >= limit:
                        break
            
            logger.info(f"Total de músicas extraídas: {len(result)}")
            return result
            
        except requests.RequestException as e:
            logger.error(f"Erro na requisição HTTP: {e}")
            return []
        except Exception as e:
            logger.error(f"Erro ao extrair músicas: {e}")
            return []

    def save_musics_to_supabase(self, musics: List[Dict]) -> int:
        """Salva as músicas no Supabase"""
        if not self.supabase:
            logger.warning("Supabase não configurado. Não há dados salvos no Supabase.")
            return 0

        saved_count = 0
        
        for music in musics:
            try:
                # Salva o gênero se novo
                if music.get('genre') and music['genre'] not in self.processed_genre_names:
                    try:
                        existing = self.supabase.table('genres').select('id').eq('name', music['genre']).execute()
                        if not existing.data:
                            self.supabase.table('genres').insert({
                                'name': music['genre'],
                                'slug': music['genre'].lower().replace(' ', '-')
                            }).execute()
                            logger.info(f"📁 Gênero salvo: {music['genre']}")
                        self.processed_genre_names.add(music['genre'])
                    except Exception as e:
                        logger.warning(f"Erro ao salvar gênero {music['genre']}: {e}")

                # Salva o artista se novo
                artist_id = None
                if music.get('artist_slug'):
                    try:
                        existing = self.supabase.table('artists').select('id').eq('slug', music['artist_slug']).execute()
                        if not existing.data:
                            artist_id = self._generate_id('art_', 16)
                            self.supabase.table('artists').insert({
                                'id': artist_id,
                                'name': music['artist_name'],
                                'slug': music['artist_slug'],
                                'genre': music.get('genre', 'Música')
                            }).execute()
                            logger.info(f"👤 Artista salvo: {music['artist_name']}")
                        else:
                            artist_id = existing.data[0]['id']
                    except Exception as e:
                        logger.warning(f"Erro ao salvar artista {music['artist_name']}: {e}")

                # Salva a música
                try:
                    existing = self.supabase.table('musics').select('id').eq('id', music['id']).execute()
                    if not existing.data:
                        self.supabase.table('musics').insert({
                            'id': music['id'],
                            'title': music['title'],
                            'artist_id': artist_id,
                            'artist_name': music['artist_name'],
                            'artist_slug': music['artist_slug'],
                            'album': music.get('album'),
                            'release_year': music.get('release_year'),
                            'genre': music.get('genre'),
                            'plays': music.get('plays', 0),
                            'cover_url': music.get('cover_url'),
                            'mp3_url': music.get('mp3_url'),
                            'palcomp3_url': music.get('palcomp3_url'),
                            'duration': music.get('duration')
                        }).execute()
                        saved_count += 1
                        logger.info(f"✅ Música salva: {music['title']} - {music['artist_name']}")
                except Exception as e:
                    logger.warning(f"Erro ao salvar música {music['title']}: {e}")
                    
            except Exception as e:
                logger.error(f"Erro ao processar música: {e}")
        
        return saved_count

    def run(self, limit: int = None):
        """Executa o scraper completo, iterando por todos os gêneros encontrados"""
        logger.info("🚀 Iniciando scraper do Radio Ao Vivo")
        
        total_saved = 0
        all_musics = []
        
        # Descobre todos os gêneros disponíveis
        genres = self._discover_genre_urls()
        
        # Se encontrou gêneros, itera sobre cada um
        if genres:
            logger.info(f"📋 Encontrados {len(genres)} gêneros para processar")
            for genre in genres:
                logger.info(f"🎯 Processando gênero: {genre['name']}")
                musics = self.scrape_top_songs(
                    limit=limit,
                    genre_url=genre['url'],
                    genre_name=genre['name']
                )
                all_musics.extend(musics)
                logger.info(f"   → {len(musics)} músicas encontradas em {genre['name']}")
        else:
            # Fallback: extrai da página principal
            logger.info("📋 Nenhum gênero específico encontrado, usando página principal")
            musics = self.scrape_top_songs(limit)
            all_musics.extend(musics)
        
        if all_musics:
            if self.supabase:
                saved = self.save_musics_to_supabase(all_musics)
                logger.info(f"✅ {saved} músicas salvas com sucesso no Supabase!")
            else:
                logger.error("Supabase não configurado. Defina SUPABASE_URL/SUPABASE_KEY para salvar os resultados no Supabase.")
        else:
            logger.warning("⚠️ Nenhuma música encontrada para salvar")
        
        logger.info("🏁 Scraper finalizado!")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    scraper = RadioAOVivoScraper()
    scraper.run(limit=100)  # Limite de 100 músicas