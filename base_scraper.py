"""
Classe base para scrapers do Palco MP3.
Contém funcionalidades compartilhadas: Selenium, Supabase, helpers.
"""

import os
import re
import time
import uuid
import logging
import sys
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from supabase import create_client, Client
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ProgressManager:
    """
    Gerenciador de barras de progresso que NUNCA desaparece.
    Usa tqdm com position fixa para manter as barras visíveis.
    """
    def __init__(self):
        self.bars = {}  # name -> tqdm instance
    
    def create_bar(self, name: str, total: int, desc: str = "", unit: str = "it", position: int = 0):
        """Cria ou recria uma barra de progresso"""
        from tqdm import tqdm
        
        if name in self.bars:
            self.bars[name].close()
        
        bar = tqdm(
            total=total,
            desc=desc,
            unit=unit,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]  {postfix}",
            position=position,
            leave=True,  # NUNCA desaparece
            file=sys.stderr,
            dynamic_ncols=True,
        )
        self.bars[name] = bar
        return bar
    
    def update(self, name: str, n: int = 1, postfix: str = ""):
        """Atualiza uma barra de progresso"""
        if name in self.bars:
            self.bars[name].update(n)
            if postfix:
                self.bars[name].set_postfix_str(postfix, refresh=True)
    
    def set_total(self, name: str, total: int):
        """Altera o total de uma barra"""
        if name in self.bars:
            self.bars[name].total = total
            self.bars[name].refresh()
    
    def set_desc(self, name: str, desc: str):
        """Altera a descrição de uma barra"""
        if name in self.bars:
            self.bars[name].set_description(desc)
    
    def close(self, name: str):
        """Fecha uma barra específica"""
        if name in self.bars:
            self.bars[name].close()
            del self.bars[name]
    
    def close_all(self):
        """Fecha TODAS as barras"""
        for name in list(self.bars.keys()):
            self.close(name)
    
    def write(self, msg: str):
        """Escreve uma mensagem sem atrapalhar as barras"""
        from tqdm import tqdm
        try:
            tqdm.write(msg)
        except UnicodeEncodeError:
            # Fallback: remove caracteres que nao cabem em cp1252
            tqdm.write(msg.encode('cp1252', errors='replace').decode('cp1252'))


# Instância global de ProgressManager
progress = ProgressManager()


class PalcoBaseScraper:
    """Classe base com funcionalidades compartilhadas entre scrapers"""

    BASE_URL = "https://www.palcomp3.com.br"
    BATCH_SIZE = 1000  # Tamanho do lote para batch inserts no Supabase (aumentado para máxima velocidade)

    # Lista de gêneros conhecidos para detectar no nome das playlists
    KNOWN_GENRES = [
        'Sertanejo', 'Forró', 'Forro', 'Funk', 'Rock', 'Pop', 'MPB',
        'Eletrônica', 'Eletronica', 'Hip Hop', 'Hip-Hop', 'Rap',
        'Reggae', 'Samba', 'Pagode', 'Axé', 'Axe', 'Gospel',
        'Brega', 'Trap', 'Arrocha', 'Vaquejada', 'Country',
        'Blues', 'Jazz', 'Clássica', 'Classical', 'Indie',
        'Romântico', 'Romantico', 'Infantil', 'Religioso',
        'Alternativo', 'Sertanejo Universitário', 'Católica', 'Católico',
    ]
    # Mapeamento de palavras-chave para generos (funciona com nomes de artistas)
    GENRE_KEYWORDS = {
        'sertanejo': 'Sertanejo', 'sertaneja': 'Sertanejo', 'modão': 'Sertanejo',
        'moda de viola': 'Sertanejo', 'violeiro': 'Sertanejo', 'dupla': 'Sertanejo',
        'forro': 'Forró', 'forró': 'Forró', 'vaquejada': 'Vaquejada',
        'funk': 'Funk', 'rock': 'Rock', 'pop': 'Pop',
        'mpb': 'MPB', 'samba': 'Samba', 'pagode': 'Pagode',
        'axe': 'Axé', 'axé': 'Axé', 'gospel': 'Gospel', 'evangelico': 'Gospel',
        'brega': 'Brega', 'trap': 'Trap', 'arrocha': 'Arrocha',
        'reggae': 'Reggae', 'rap': 'Rap', 'hip hop': 'Hip Hop',
        'eletronica': 'Eletrônica', 'eletrônica': 'Eletrônica',
        'classica': 'Clássica', 'clássica': 'Clássica',
        'blues': 'Blues', 'jazz': 'Jazz', 'country': 'Country',
        'indie': 'Indie', 'romantico': 'Romântico', 'romântico': 'Romântico',
        'infantil': 'Infantil', 'religioso': 'Religioso', 'alternativo': 'Alternativo',
        'catolica': 'Católica', 'católica': 'Católica', 'catolico': 'Católica', 'católico': 'Católica',
    }

    def __init__(self):
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_KEY')
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment variables")

        # Suprime warning "Connection pool is full" do Supabase (httpx interno)
        # Não é um erro fatal - apenas significa que o pool de 1 conexão está cheio
        logging.getLogger('httpx').setLevel(logging.ERROR)
        logging.getLogger('httpcore').setLevel(logging.ERROR)
        
        self.supabase: Client = create_client(self.supabase_url, self.supabase_key)

        # Sessão otimizada para Palco MP3 com pool de conexões GRANDE
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # Configura pool de conexões para evitar o warning "Connection pool is full"
        # pool_connections: número de pools de conexão distintos (por host)
        # pool_maxsize: número máximo de conexões por pool
        adapter = HTTPAdapter(
            pool_connections=50,
            pool_maxsize=100,
            max_retries=Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
            )
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        # Inicializa Selenium para scroll infinito / cliques em botões
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        # Explicitamente define o caminho do executável do Chrome (necessário quando não está no PATH)
        chrome_options.binary_location = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)

        # Track processed items to avoid duplicates
        self.processed_playlist_ids = set()
        self.processed_music_ids = set()
        self.processed_artist_slugs = set()
        self.processed_genre_names = set()

    def __del__(self):
        try:
            self.driver.quit()
        except:
            pass

    def _clean_text(self, text: str) -> str:
        if not text:
            return ''
        return ' '.join(text.strip().split())

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrai ID numérico de uma URL"""
        match = re.search(r'/(\d+)', url)
        return match.group(1) if match else None

    def _generate_id(self, prefix: str = '') -> str:
        return f"{prefix}{uuid.uuid4().hex[:16]}"

    def _detect_genre_from_name(self, name: str) -> Optional[str]:
        """Detecta o gênero musical a partir do nome da playlist/música/artista"""
        if not name:
            return None
        name_lower = name.lower()
        # Primeiro tenta o mapeamento de keywords (mais abrangente)
        for keyword, genre in self.GENRE_KEYWORDS.items():
            if keyword in name_lower:
                return genre
        # Fallback: lista simples de generos
        for genre in self.KNOWN_GENRES:
            if genre.lower() in name_lower:
                return genre
        return None

    def _extract_plays(self, text: str) -> int:
        if not text:
            return 0
        cleaned = re.sub(r'[.,\s]', '', text)
        match = re.search(r'\d+', cleaned)
        return int(match.group()) if match else 0

    def _scrape_artist_image(self, artist_slug: str) -> Optional[str]:
        """Extrai a imagem do artista da página do artista no Palco MP3"""
        try:
            url = f"{self.BASE_URL}/{artist_slug}/"
            response = self.session.get(url, timeout=30)
            if response.status_code != 200:
                return None
            soup = BeautifulSoup(response.text, 'html.parser')

            # Tenta og:image primeiro
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                img_url = og_image.get('content')
                # Tenta pegar tamanho maior
                if '/100x100/' in img_url:
                    img_url = img_url.replace('/100x100/', '/500x500/')
                elif '/160x160/' in img_url:
                    img_url = img_url.replace('/160x160/', '/500x500/')
                return img_url

            # Tenta encontrar a imagem do artista na página
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src') or ''
                alt = (img.get('alt') or '').lower()
                if 'logo' in src.lower() or 'avatar' in src.lower() or 'artist' in src.lower():
                    if src.startswith('http'):
                        if '/100x100/' in src:
                            src = src.replace('/100x100/', '/500x500/')
                        elif '/160x160/' in src:
                            src = src.replace('/160x160/', '/500x500/')
                        return src

            for img in soup.find_all('img'):
                src = img.get('src') or ''
                if 'sscdn' in src or 'akamaized' in src or 'palcomp3' in src:
                    if '/160x160/' in src:
                        src = src.replace('/160x160/', '/500x500/')
                    elif '/100x100/' in src:
                        src = src.replace('/100x100/', '/500x500/')
                    return src

            return None
        except Exception as e:
            logger.warning(f"Erro ao buscar imagem do artista {artist_slug}: {e}")
            return None

    def _scrape_music_mp3_url(self, palcomp3_url: str) -> Optional[str]:
        """Extrai o MP3 URL de uma página de música individual"""
        try:
            response = self.session.get(palcomp3_url, timeout=30)
            if response.status_code != 200:
                return None
            soup = BeautifulSoup(response.text, 'html.parser')

            audio = soup.find('audio')
            if audio and audio.get('src'):
                return audio.get('src')

            for link in soup.find_all('a', href=re.compile(r'\.mp3', re.I)):
                mp3_url = link.get('href')
                if mp3_url:
                    return mp3_url if mp3_url.startswith('http') else urljoin(self.BASE_URL, mp3_url)

            for elem in soup.find_all(attrs={'data-mp3': True}):
                mp3_url = elem.get('data-mp3')
                if mp3_url:
                    return mp3_url if mp3_url.startswith('http') else urljoin(self.BASE_URL, mp3_url)

            for script in soup.find_all('script'):
                script_text = script.string or ''
                mp3_match = re.search(r'["\']([^"\']*\.mp3[^"\']*)["\']', script_text, re.I)
                if mp3_match:
                    mp3_url = mp3_match.group(1)
                    return mp3_url if mp3_url.startswith('http') else urljoin(self.BASE_URL, mp3_url)

            return None
        except Exception as e:
            logger.warning(f"Erro ao buscar MP3 para {palcomp3_url}: {e}")
            return None

    def _scrape_music_cover_url(self, palcomp3_url: str) -> Optional[str]:
        """Extrai a capa da música da página individual"""
        try:
            response = self.session.get(palcomp3_url, timeout=30)
            if response.status_code != 200:
                return None
            soup = BeautifulSoup(response.text, 'html.parser')

            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                cover_url = og_image.get('content')
                if '/100x100/' in cover_url:
                    cover_url = cover_url.replace('/100x100/', '/500x500/')
                return cover_url

            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if src and ('cover' in src.lower() or 'album' in src.lower()):
                    if '/100x100/' in src:
                        src = src.replace('/100x100/', '/500x500/')
                    return src

            return None
        except:
            return None

    # ----------------------------------------------------------------
    #  UTILITÁRIOS DE BATCH INSERT PARA SUPABASE (OTIMIZADOS)
    # ----------------------------------------------------------------

    def _batch_insert(self, table: str, records: List[Dict], conflict_check_col: str = None, conflict_value_col: str = None) -> int:
        """
        Insere registros em lote no Supabase.
        Muito mais rápido que inserir um por um.
        
        Args:
            table: Nome da tabela
            records: Lista de dicionários com os dados
            conflict_check_col: Coluna para verificar duplicatas (ex: 'palcomp3_url')
            conflict_value_col: Se diferente da coluna de checagem, usa este valor
            
        Returns:
            Número de registros inseridos
        """
        if not records:
            return 0

        # Remove duplicatas que já existem no banco
        if conflict_check_col:
            existing_values = set()
            try:
                all_values = [r.get(conflict_value_col or conflict_check_col) for r in records if r.get(conflict_value_col or conflict_check_col)]
                for i in range(0, len(all_values), 100):
                    batch_values = all_values[i:i + 100]
                    result = (
                        self.supabase.table(table)
                        .select(conflict_check_col)
                        .in_(conflict_check_col, batch_values)
                        .execute()
                    )
                    for row in result.data:
                        existing_values.add(row[conflict_check_col])
            except Exception:
                pass
            
            records = [r for r in records if r.get(conflict_value_col or conflict_check_col) not in existing_values]

        if not records:
            return 0

        # Insere em lotes
        total_inserted = 0
        for i in range(0, len(records), self.BATCH_SIZE):
            batch = records[i:i + self.BATCH_SIZE]
            try:
                self.supabase.table(table).insert(batch).execute()
                total_inserted += len(batch)
            except Exception as e:
                logger.warning(f"   ⚠️ Erro no batch insert em {table} ({len(batch)} registros): {e}")
                # Fallback: insere um por um
                for record in batch:
                    try:
                        self.supabase.table(table).insert(record).execute()
                        total_inserted += 1
                    except Exception as e2:
                        logger.debug(f"      ⚠️ Erro ao inserir registro em {table}: {e2}")

        return total_inserted

    def _batch_upsert(self, table: str, records: List[Dict], conflict_col: str) -> int:
        """
        Faz upsert (insert or update) em lote no Supabase.
        
        Args:
            table: Nome da tabela
            records: Lista de dicionários com os dados
            conflict_col: Coluna de conflito para upsert (ex: 'palcomp3_url')
            
        Returns:
            Número de registros processados
        """
        if not records:
            return 0

        total = 0
        for i in range(0, len(records), self.BATCH_SIZE):
            batch = records[i:i + self.BATCH_SIZE]
            try:
                self.supabase.table(table).upsert(batch, on_conflict=conflict_col).execute()
                total += len(batch)
            except Exception as e:
                logger.warning(f"   ⚠️ Erro no batch upsert em {table}: {e}")
                for record in batch:
                    try:
                        self.supabase.table(table).upsert(record, on_conflict=conflict_col).execute()
                        total += 1
                    except Exception:
                        pass

        return total