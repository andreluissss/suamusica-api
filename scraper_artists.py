"""
Palco MP3 Artist Scraper - Extrai TODOS os artistas (A-Z, 0-9) e suas musicas.
Uso: python scraper_artists.py
     python scraper_artists.py --limit 5
     python scraper_artists.py --limit 5 --parallel 5
"""

import os, re, time, json, logging, sys, concurrent.futures, threading
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import urljoin
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import ast as ast_lib
from base_scraper import PalcoBaseScraper, logger, progress


class PalcoArtistScraper(PalcoBaseScraper):
    LETTERS = [c for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789']
    SKIP_SLUGS = {'top-artistas','top-musicas','playlists','podcasts','mp3',
                  'playlist','podcast','login','cadastro','contato','busca',
                  'sobre','termos','politica','artistas','musicas'}

    def __init__(self, max_artists_per_letter=None, max_musics_per_artist=None, parallel_workers=3):
        super().__init__()
        self.max_artists_per_letter = max_artists_per_letter
        self.max_musics_per_artist = max_musics_per_artist
        self.parallel_workers = parallel_workers
        # Lock exclusivo para o driver Selenium (compartilhado entre threads)
        self._driver_lock = threading.Lock()

    def _clean_artist_name(self, raw_text, slug):
        if not raw_text: return slug.replace('-', ' ').title()
        cleaned = self._clean_text(raw_text)
        if len(cleaned) < 2: return slug.replace('-', ' ').title()
        for genre in self.KNOWN_GENRES:
            g = genre.lower()
            while g in cleaned.lower():
                i = cleaned.lower().find(g)
                cleaned = cleaned[:i] + cleaned[i+len(genre):]
                cleaned = self._clean_text(cleaned)
        cleaned = self._clean_text(cleaned)
        if len(cleaned) < 2: return slug.replace('-', ' ').title()
        for sp in range(len(cleaned)//2, 1, -1):
            if cleaned[:sp].strip() and cleaned[:sp].strip().lower() == cleaned[sp:].strip().lower():
                cleaned = cleaned[:sp].strip(); break
        cleaned = self._clean_text(cleaned.strip('/-|--:;,. '))
        return cleaned if len(cleaned) >= 2 else slug.replace('-', ' ').title()

    def _scrape_artists_from_letter_page(self, letter):
        url = f"{self.BASE_URL}/mp3/{letter}/"
        progress.write(f"[LETTER] {letter} -> {url}")
        self.driver.get(url); time.sleep(4)
        
        # Tenta clicar em "Ver mais" para carregar todos os artistas
        for _ in range(10):
            try:
                clicked = False
                # XPaths para o botao "Ver mais" na pagina de letra
                for xp in ["//*[@id='content']/div/button", "//*[@id='content']/div/div/button"]:
                    try:
                        e = self.driver.find_element(By.XPATH, xp)
                        if e.is_displayed() and e.is_enabled():
                            self.driver.execute_script("arguments[0].scrollIntoView(true);", e); time.sleep(1)
                            self.driver.execute_script("arguments[0].click();", e); time.sleep(3); clicked = True
                            progress.write(f"      [CLICK] Botao encontrado com XPath: {xp}")
                            break
                    except: pass
                if not clicked: break
            except: break
        
        # Scroll ate o final para garantir que tudo carregou
        last_h = self.driver.execute_script("return document.body.scrollHeight")
        for _ in range(5):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(2)
            nh = self.driver.execute_script("return document.body.scrollHeight")
            if nh == last_h: break
            last_h = nh
        
        # Extrai a lista de artistas do Apollo State (fonte oficial e completa)
        # O Apollo State na pagina de letra contem a query alphabet com TODOS os artistas
        page_html = self.driver.page_source
        marker = 'window.__APOLLO_STATE__="'
        idx = page_html.find(marker)
        artists = []
        
        if idx >= 0:
            start = idx + len(marker)
            end = page_html.find('";', start)
            if end >= 0:
                raw = page_html[start:end]
                try:
                    unescaped = raw.encode('utf-8').decode('unicode_escape')
                    state = json.loads(unescaped)
                    
                    # Procura pela conexao alphabet que tem todos os artistas
                    for key, val in state.items():
                        if isinstance(val, dict):
                            typename = val.get('__typename', '')
                            # A conexao de artistas tem edges com nodes
                            edges = val.get('edges', None)
                            if edges and typename and 'Artist' in typename and isinstance(edges, list):
                                for edge in edges:
                                    if isinstance(edge, dict):
                                        node = edge.get('node', {})
                                        if isinstance(node, dict):
                                            node_id = node.get('id', '')
                                            if node_id.startswith('$'):
                                                node_id = node_id[1:]
                                            artist_data = state.get(node_id, {})
                                            if isinstance(artist_data, dict) and artist_data.get('__typename') == 'Artist':
                                                slug = artist_data.get('slug', '')
                                                name = artist_data.get('name', slug.replace('-', ' ').title())
                                                if slug and slug not in self.processed_artist_slugs and slug not in self.SKIP_SLUGS:
                                                    # Pega thumbnail do artista
                                                    img_url = None
                                                    thumb = artist_data.get('thumbnail', {})
                                                    if isinstance(thumb, dict) and thumb.get('id'):
                                                        th_key = thumb['id']
                                                        if th_key.startswith('$'):
                                                            th_key = th_key[1:]
                                                        th = state.get(th_key, {})
                                                        if isinstance(th, dict):
                                                            img_url = th.get('url', '') or th.get('url2x', '')
                                                            if img_url and '/160x160/' in img_url:
                                                                img_url = img_url.replace('/160x160/', '/500x500/')
                                                            elif img_url and '/100x100/' in img_url:
                                                                img_url = img_url.replace('/100x100/', '/500x500/')
                                                    
                                                    artists.append({
                                                        'slug': slug,
                                                        'name': name,
                                                        'image_url': img_url,
                                                        'palcomp3_url': urljoin(self.BASE_URL, f"/{slug}/")
                                                    })
                                                    self.processed_artist_slugs.add(slug)
                                
                                if artists:
                                    break  # Ja encontrou a lista de artistas
                except Exception as e:
                    logger.debug(f"Erro ao parsear Apollo State da letra {letter}: {e}")
        
        # Fallback: se Apollo State falhou, extrai do HTML
        if not artists:
            soup = BeautifulSoup(page_html, 'html.parser')
            all_letters = set(l.lower() for l in self.LETTERS)
            for a in soup.find_all('a', href=True):
                h = a.get('href','').strip()
                m = re.match(r'^/([a-z0-9][a-z0-9-]*[a-z0-9]?)/?$', h, re.I)
                if not m: continue
                s = m.group(1).lower()
                if s in all_letters or s in self.SKIP_SLUGS or s.startswith('search') or s.startswith('tag') or s in self.processed_artist_slugs:
                    continue
                name = self._clean_artist_name(a.get_text(), s)
                img = a.find('img')
                img_url = None
                if img:
                    img_url = img.get('src') or img.get('data-src')
                    if img_url:
                        if not img_url.startswith('http'): img_url = urljoin(self.BASE_URL, img_url)
                        if '/100x100/' in img_url: img_url = img_url.replace('/100x100/','/500x500/')
                        elif '/160x160/' in img_url: img_url = img_url.replace('/160x160/','/500x500/')
                artists.append({'slug':s,'name':name,'image_url':img_url,'palcomp3_url':urljoin(self.BASE_URL,h)})
                self.processed_artist_slugs.add(s)
        
        progress.write(f"   [DONE] {letter}: {len(artists)} artistas")
        return artists

    def _extract_apollo_data(self, html_text):
        """
        Extrai MP3s, covers, titulos do Apollo State a partir do HTML da pagina do artista.
        O Apollo State fica inline no HTML como:
          <script>window.__APOLLO_STATE__="...JSON..."</script>
        
        Retorna (mp3_map, cover_map, title_map, img_url)
        """
        mp3_map, cover_map, title_map, img = {}, {}, {}, None
        
        # Procura pelo Apollo State no HTML
        marker = 'window.__APOLLO_STATE__="'
        idx = html_text.find(marker)
        if idx < 0:
            return mp3_map, cover_map, title_map, None
        
        start = idx + len(marker)
        end = html_text.find('";', start)
        if end < 0:
            return mp3_map, cover_map, title_map, None
        
        raw = html_text[start:end]
        
        try:
            # Primeiro tenta unescape da string JS
            unescaped = raw.encode('utf-8').decode('unicode_escape')
            state = json.loads(unescaped)
        except Exception:
            try:
                # Fallback: ast.literal_eval
                state = json.loads(ast_lib.literal_eval('"' + raw + '"'))
            except Exception:
                return mp3_map, cover_map, title_map, None
        
        # Extrai dados de todas as Music entries no Apollo State
        for key, val in state.items():
            if not isinstance(val, dict):
                continue
            typename = val.get('__typename', '')
            if typename != 'Music':
                continue
            
            slug = val.get('slug', '')
            if not slug:
                continue
            sc = slug.strip().lower()
            
            # Título
            title = val.get('title', '')
            if title:
                title_map[sc] = title
            
            # MP3 URL
            mp3 = val.get('mp3File', '')
            if mp3:
                if mp3.startswith('//'):
                    mp3 = 'https:' + mp3
                elif not mp3.startswith('http'):
                    mp3 = urljoin(self.BASE_URL, mp3)
                mp3_map[sc] = mp3
            
            # Cover URL - tenta pegar do disco associado
            cover = val.get('coverUrl', '') or val.get('image', '') or val.get('cover', '')
            if cover:
                if cover.startswith('//'):
                    cover = 'https:' + cover
                elif not cover.startswith('http'):
                    cover = urljoin(self.BASE_URL, cover)
                if '/100x100/' in cover:
                    cover = cover.replace('/100x100/', '/500x500/')
                elif '/160x160/' in cover:
                    cover = cover.replace('/160x160/', '/500x500/')
                cover_map[sc] = cover
            
            # Se não tem cover direto, tenta pegar do disco via referência
            if sc not in cover_map:
                disc_refs = val.get('discIDs', {}).get('json', [])
                if disc_refs:
                    # Procura discos no state
                    for dk, dv in state.items():
                        if isinstance(dv, dict) and dv.get('__typename') == 'Disc':
                            if dv.get('discID') in disc_refs:
                                pic = dv.get('picture', {})
                                if isinstance(pic, dict) and pic.get('id'):
                                    # Segue a referência
                                    pic_key = pic['id']
                                    if pic_key.startswith('$'):
                                        pic_key = pic_key[1:]
                                    pic_data = state.get(pic_key, {})
                                    if isinstance(pic_data, dict):
                                        url = pic_data.get('url', '')
                                        if url:
                                            if '/100x100/' in url:
                                                url = url.replace('/100x100/', '/500x500/')
                                            elif '/160x160/' in url:
                                                url = url.replace('/160x160/', '/500x500/')
                                            cover_map[sc] = url
                                            break
        
        # Tenta extrair imagem do artista do state
        for key, val in state.items():
            if isinstance(val, dict) and val.get('__typename') == 'Artist':
                # Tenta avatar
                avatar_ref = val.get('avatar', {})
                if isinstance(avatar_ref, dict) and avatar_ref.get('id'):
                    av_key = avatar_ref['id']
                    if av_key.startswith('$'):
                        av_key = av_key[1:]
                    av_data = state.get(av_key, {})
                    if isinstance(av_data, dict):
                        av_url = av_data.get('original', '')
                        if av_url and not img:
                            img = av_url
                            if '/100x100/' in img:
                                img = img.replace('/100x100/', '/500x500/')
                            elif '/160x160/' in img:
                                img = img.replace('/160x160/', '/500x500/')
                
                # Tenta thumbnail
                if not img:
                    thumb_ref = val.get('thumbnail', {})
                    if isinstance(thumb_ref, dict) and thumb_ref.get('id'):
                        th_key = thumb_ref['id']
                        if th_key.startswith('$'):
                            th_key = th_key[1:]
                        th_data = state.get(th_key, {})
                        if isinstance(th_data, dict):
                            th_url = th_data.get('url', '')
                            if th_url:
                                img = th_url
                                if '/100x100/' in img:
                                    img = img.replace('/100x100/', '/500x500/')
                                elif '/160x160/' in img:
                                    img = img.replace('/160x160/', '/500x500/')
        
        return mp3_map, cover_map, title_map, img

    def _scrape_artist_musics(self, artist_slug):
        progress.write(f"   [MUSIC] {artist_slug}")
        try:
            # Lock exclusivo: apenas uma thread usa o Selenium por vez
            with self._driver_lock:
                # Tenta acessar /todas_musicas.htm primeiro (tem todas as músicas)
                # Se não existir, tenta /musicas.htm (músicas mais acessadas)
                # Se não existir, usa página principal e clica no botão
                urls_to_try = [
                    f"{self.BASE_URL}/{artist_slug}/todas_musicas.htm",
                    f"{self.BASE_URL}/{artist_slug}/musicas.htm",
                    f"{self.BASE_URL}/{artist_slug}/"
                ]
                
                page_loaded = False
                for url in urls_to_try:
                    try:
                        self.driver.get(url); time.sleep(0.5)
                        page_loaded = True
                        break
                    except Exception:
                        continue
                
                if not page_loaded:
                    return [], None, None, {'style': None, 'city': None, 'state': None, 'total_plays': None}
                
                # Tenta clicar em "Ver mais" / "Ver todas" usando seletores mais robustos
                for _ in range(10):
                    try:
                        clicked = False
                        # Procura por links e botoes que contenham texto relevante
                        for e in self.driver.find_elements(By.TAG_NAME, "button") + self.driver.find_elements(By.TAG_NAME, "a"):
                            txt = e.text.strip().lower()
                            if any(w in txt for w in ['ver mais','ver todas','Carregar mais','mais musicas','ver','todas','carregar']):
                                if e.is_displayed() and e.is_enabled():
                                    self.driver.execute_script("arguments[0].scrollIntoView(true);", e); time.sleep(0.3)
                                    self.driver.execute_script("arguments[0].click();", e); time.sleep(0.5); clicked = True; break
                        if not clicked: break
                    except: break
                
                # Scroll para carregar conteudo lazy (otimizado para velocidade)
                last_h = self.driver.execute_script("return document.body.scrollHeight")
                for _ in range(5):
                    self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(0.5)
                    nh = self.driver.execute_script("return document.body.scrollHeight")
                    if nh == last_h: break
                    last_h = nh
                
                page_html = self.driver.page_source
            
            soup = BeautifulSoup(page_html, 'html.parser')
            musics = []; artist_name = None; artist_image = None
            
            # Extrai informações do cabeçalho do artista (estilo, cidade/estado, plays)
            header_info = {'style': None, 'city': None, 'state': None, 'total_plays': None}
            try:
                # Tenta extrair estilo do HTML da página (mais robusto que Selenium)
                # Procura por links de gênero que apontam para /mp3/genero/
                genre_links = soup.find_all('a', href=re.compile(r'/mp3/[^/]+/$'))
                for link in genre_links:
                    href = link.get('href', '')
                    # Verifica se é um link de gênero válido
                    if href.startswith('/mp3/') and href.endswith('/') and len(href.split('/')) == 4:
                        genre_name = link.text.strip()
                        if genre_name and len(genre_name) > 2:
                            header_info['style'] = genre_name
                            logger.debug(f"Gênero encontrado no HTML: {genre_name}")
                            break
                
                # Se não encontrou no HTML, tenta via Selenium
                if not header_info['style']:
                    # Procura pelo div _17c_w que contém as informações do artista (estilo, cidade, plays)
                    # Estrutura: 3 divs filhas: [Estilo + Sertanejo], [Cidade/Estado + SP/SP], [Plays + 583.959]
                    info_div = None
                    selectors = [
                        (By.CSS_SELECTOR, '[class*="_17c_w"]'),
                        (By.XPATH, '//*[@id="content"]/div/section/header/div[3]/div[2]'),
                    ]
                    for by, selector in selectors:
                        try:
                            info_div = self.driver.find_element(by, selector)
                            if info_div:
                                break
                        except:
                            continue
                    
                    if info_div:
                        child_divs = info_div.find_elements(By.XPATH, './div')
                        for child in child_divs:
                            text = child.text.strip()
                            # Div de Estilo: contém "<small>Estilo</small><a><b>Sertanejo</b></a>"
                            if 'Estilo' in text:
                                try:
                                    b_tag = child.find_element(By.TAG_NAME, 'b')
                                    header_info['style'] = b_tag.text.strip()
                                except:
                                    try:
                                        a_tag = child.find_element(By.TAG_NAME, 'a')
                                        header_info['style'] = a_tag.text.strip()
                                    except:
                                        pass
                            # Div de Plays: contém "<small>Plays</small><b>583.959<span>plays</span></b>"
                            elif 'Plays' in text or 'plays' in text:
                                try:
                                    b_tag = child.find_element(By.TAG_NAME, 'b')
                                    plays_text = b_tag.text.strip()
                                    plays_match = re.search(r'([\d.,]+)', plays_text)
                                    if plays_match:
                                        header_info['total_plays'] = plays_match.group(1).replace('.', '').replace(',', '')
                                except:
                                    pass
                            # Div de Cidade/Estado: contém "<small>Cidade/Estado</small><b>São Paulo / SP</b>"
                            elif 'Cidade' in text or 'Estado' in text:
                                try:
                                    b_tag = child.find_element(By.TAG_NAME, 'b')
                                    location_text = b_tag.text.strip()
                                    parts = location_text.split('/')
                                    if len(parts) >= 1:
                                        header_info['city'] = parts[0].strip()
                                    if len(parts) >= 2:
                                        header_info['state'] = parts[1].strip()
                                except:
                                    pass
                        
                        logger.debug(f"Header info para {artist_slug}: style={header_info['style']}, plays={header_info['total_plays']}")
                    else:
                        logger.warning(f"Elemento de cabeçalho não encontrado para {artist_slug}")
                    
            except Exception as e:
                logger.warning(f"Erro ao extrair header info para {artist_slug}: {e}")
            
            # Extrai nome do artista do og:title
            og = soup.find('meta', property='og:title')
            if og: artist_name = re.sub(r'\s*[-|]\s*Palco\s*MP3.*$', '', og.get('content','').strip(), flags=re.I).strip()
            
            # Extrai imagem do artista do og:image
            og = soup.find('meta', property='og:image')
            if og and og.get('content'):
                artist_image = og.get('content')
                if '/100x100/' in artist_image: artist_image = artist_image.replace('/100x100/','/500x500/')
                elif '/160x160/' in artist_image: artist_image = artist_image.replace('/160x160/','/500x500/')
            
            # Extrai Apollo State do HTML da pagina (ja carregada pelo Selenium)
            mp3_map, cover_map, title_map, apollo_img = self._extract_apollo_data(page_html)
            if apollo_img and not artist_image: artist_image = apollo_img
            progress.write(f"      [APOLLO] {len(mp3_map)} MP3s, {len(cover_map)} covers, {len(title_map)} titulos")
            
            # Coleta slugs de musicas do Apollo State + HTML
            all_slugs = set(mp3_map.keys()) | set(cover_map.keys()) | set(title_map.keys())
            
            # Tambem coleta slugs dos links de musica no HTML
            pat = re.compile(r'^/' + re.escape(artist_slug) + r'/[a-z0-9][a-z0-9-]*/?$', re.I)
            ignore_slugs = {'playlist', 'playlists', 'podcast', 'podcasts', 'top-artistas', 'top-musicas', 
                           'mp3', 'login', 'cadastro', 'musicas', 'discografia', 'clipes', 'integrantes',
                           'musica', 'album', 'albuns'}
            for a in soup.find_all('a', href=True):
                h = a.get('href','').strip()
                if pat.match(h):
                    p = h.strip('/').split('/')
                    if len(p) >= 2 and p[-1].lower() != artist_slug.lower() and p[-1].lower() not in ignore_slugs:
                        all_slugs.add(p[-1].lower())
            
            progress.write(f"      [SLUGS] {len(all_slugs)} musicas unicas")
            pos = 0
            for ms in sorted(all_slugs):
                if self.max_musics_per_artist and pos >= self.max_musics_per_artist: break
                pos += 1
                try:
                    msl = ms.lower(); mid = self._generate_id('')
                    title = title_map.get(msl)
                    if not title or len(title) < 2:
                        a = soup.find('a', href=f"/{artist_slug}/{ms}/")
                        if a: title = self._clean_text(a.get_text())
                    if not title or len(title) < 2: title = ms.replace('-',' ').title()
                    
                    plays = 0
                    a = soup.find('a', href=f"/{artist_slug}/{ms}/")
                    if a:
                        for p in [a.parent, a.parent.parent if a.parent else None]:
                            if p:
                                pe = p.find(class_=re.compile(r'plays|_3hmrv|_1Ie3C', re.I))
                                if pe: plays = self._extract_plays(pe.get_text()); break
                    
                    palcomp3_url = urljoin(self.BASE_URL, f"/{artist_slug}/{ms}/")
                    genre = self._detect_genre_from_name(title)
                    mp3_url = mp3_map.get(msl) or next((v for k,v in mp3_map.items() if msl in k or k in msl), None)
                    cover_url = cover_map.get(msl) or next((v for k,v in cover_map.items() if msl in k or k in msl), None)
                    
                    musics.append({'id':mid,'title':title,'artist_slug':artist_slug,
                        'artist_name':artist_name or artist_slug.replace('-',' ').title(),
                        'genre':genre,'plays':plays,'mp3_url':mp3_url,'cover_url':cover_url,
                        'palcomp3_url':palcomp3_url,'position':pos})
                except Exception as e: logger.warning(f"      [ERR] {ms}: {e}")
            
            return musics, artist_name, artist_image, header_info
        except Exception as e:
            logger.error(f"   [ERR] {artist_slug}: {e}")
            return [], None, None, {'style': None, 'city': None, 'state': None, 'total_plays': None}

    @staticmethod
    def _sanitize(val):
        """Remove caracteres nulos (\\u0000) de strings para evitar erro do PostgreSQL"""
        if isinstance(val, str):
            return val.replace('\x00', '').replace('\\u0000', '')
        return val

    def _process_single_artist(self, artist):
        try:
            m, n, i, h = self._scrape_artist_musics(artist['slug'])
            musics = m
            name_ex = n
            img_ex = i
            header_info = h
            
            # ----- SALVAR IMEDIATAMENTE NO SUAPABASE -----
            # Usa slug completo para operacoes web, versao truncada para ID do banco (varchar 16)
            full_slug = artist['slug']
            aid = full_slug[:14]
            iurl = artist.get('image_url') or img_ex
            if not iurl:
                iurl = self._scrape_artist_image(full_slug)
            
            # Nome do Apollo State da pagina de letra (CORRETO) tem prioridade ABSOLUTA sobre nome
            # extraido do driver compartilhado (que pode ser de outro artista em modo paralelo)
            ad_name = self._sanitize(artist.get('name') or artist['slug'].replace('-',' ').title())
            
            # Detecta e remove gêneros do nome do artista para evitar interferência
            # Ex: "CatólicaAlvaro e Daniel" -> "Alvaro e Daniel" (salva "Católica" como gênero)
            # Remove TODOS os gêneros conhecidos do nome (não apenas o primeiro detectado)
            # Usa a mesma lógica robusta do _clean_artist_name
            detected_genre = self._detect_genre_from_name(ad_name)
            for genre in self.KNOWN_GENRES:
                g = genre.lower()
                while g in ad_name.lower():
                    i = ad_name.lower().find(g)
                    ad_name = ad_name[:i] + ad_name[i+len(genre):]
                    ad_name = self._clean_text(ad_name)
            ad_name = self._clean_text(ad_name.strip('/-|--:;,. '))
            if len(ad_name) < 2:
                ad_name = artist['slug'].replace('-', ' ').title()
            
            iurl = self._sanitize(iurl or '')
            
            # Deleta registros antigos para inserir novos dados atualizados
            try:
                self.supabase.table('artists').delete().eq('slug', aid).execute()
            except Exception:
                pass
            try:
                self.supabase.table('artist_musics').delete().eq('artist_slug', aid).execute()
            except Exception:
                pass
            
            # Usa o estilo do cabeçalho como gênero principal, senão usa o gênero detectado do nome
            final_genre = self._sanitize(header_info.get('style')) if header_info.get('style') else (self._sanitize(detected_genre) if detected_genre else None)
            
            # Converte total_plays para int se existir
            total_plays = None
            if header_info.get('total_plays'):
                try:
                    total_plays = int(header_info.get('total_plays'))
                except:
                    pass
            
            ad_rec = [{'id': aid, 'name': ad_name, 'slug': aid,
                       'image_url': iurl, 'palcomp3_url': self._sanitize(artist.get('palcomp3_url',
                           f"{self.BASE_URL}/{full_slug}/"))}]
            
            # Adiciona genre e total_plays apenas se não forem None
            if final_genre:
                ad_rec[0]['genre'] = final_genre
            if total_plays:
                ad_rec[0]['total_plays'] = total_plays
            
            logger.debug(f"Salvando artista {ad_name}: genre={final_genre}, total_plays={total_plays}")
            
            saved_a = self._batch_upsert('artists', ad_rec, 'slug')
            
            # Nome correto do artista (do Apollo State da pagina de letra, nao do driver compartilhado)
            correct_artist_name = ad_name
            
            # Usa o gênero detectado do nome original (antes da remoção)
            artist_genre = detected_genre
            
            # Primeiro, verifica se alguma musica tem genero detectado
            # Se sim, aplica o MESMO genero para TODAS as musicas do artista
            propagated_genre = artist_genre
            for musica in musics:
                g = self._sanitize(musica.get('genre'))
                if not g:
                    g = self._detect_genre_from_name(musica.get('title', ''))
                if g:
                    propagated_genre = g
                    break
            
            bm = []
            genre_records = []
            mini_batch_size = 50  # Envia em mini-batches para velocidade em tempo real
            saved_m = 0
            
            for i, musica in enumerate(musics):
                mp3 = self._sanitize(musica.get('mp3_url'))
                cv = self._sanitize(musica.get('cover_url'))
                # Só busca MP3 e cover se não vier do Apollo State (otimização)
                if not mp3:
                    mp3 = self._scrape_music_mp3_url(musica['palcomp3_url'])
                if not mp3:
                    continue
                if not cv:
                    cv = self._scrape_music_cover_url(musica['palcomp3_url'])
                if not cv:
                    cv = "https://via.placeholder.com/500x500"
                # Trunca o ID para caber em varchar(16) do banco
                mid = musica['id'][:14]
                # Usa o genero propagado (detectado de pelo menos uma musica do artista)
                g = propagated_genre
                
                # Coleta gêneros para salvar em batch (otimização)
                if g and g not in self.processed_genre_names:
                    genre_slug = g.lower().replace(' ', '-')
                    genre_records.append({'id': genre_slug[:14], 'name': g, 'slug': genre_slug})
                    self.processed_genre_names.add(g)
                
                bm.append({'id': mid, 'title': self._sanitize(musica['title']),
                    'artist_id': aid, 'artist_name': correct_artist_name,
                    'artist_slug': aid, 'genre': g,
                    'plays': musica.get('plays', 0), 'cover_url': cv,
                    'mp3_url': mp3, 'palcomp3_url': self._sanitize(musica['palcomp3_url'])})
                
                # Envia mini-batch em tempo real (otimização de velocidade)
                if len(bm) >= mini_batch_size:
                    saved_m += self._batch_insert('artist_musics', bm) if bm else 0
                    bm = []  # Limpa o batch para continuar acumulando
            
            # Envia o restante das músicas
            if bm:
                saved_m += self._batch_insert('artist_musics', bm) if bm else 0
            
            # Salva gêneros em batch (otimização de velocidade)
            if genre_records:
                try:
                    self._batch_upsert('genres', genre_records, 'name')
                except Exception:
                    pass
            
            progress.write(f"      [SAVED] {ad_name}: {saved_a} artista, {saved_m} musicas")
            return artist['slug'], saved_m, musics, name_ex, img_ex
        except Exception as e:
            logger.error(f"   [ERR] {artist['slug']}: {e}")
            return artist['slug'], 0, [], None, None

    def _process_artists_parallel(self, artists, letter):
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel_workers) as ex:
            fm = {ex.submit(self._process_single_artist, a): a for a in artists}
            bar = progress.create_bar(f"par_{letter}", total=len(artists), desc=f"[PAR] {letter}", unit="art", position=1)
            for f in concurrent.futures.as_completed(fm):
                a = fm[f]
                try:
                    s, n, m, nm, im = f.result()
                    results.append((s, m, nm, im))
                    bar.update(1); bar.set_postfix_str(f"{a['name'][:30]} ({n}mus)", refresh=True)
                    progress.write(f"      [OK] {a['name']}: {n} musicas")
                except Exception as e:
                    progress.write(f"   [ERR] {a['slug']}: {e}")
                    results.append((a['slug'], [], None, None)); bar.update(1)
            bar.close()
        return results

    def scrape_all_artists(self):
        total_a = total_m = 0
        for l in ('WDM','httpx','base_scraper','selenium','urllib3'): logging.getLogger(l).setLevel(logging.WARNING)
        for letter in self.LETTERS:
            progress.write(f"\n{'='*50}\n[LETTER] {letter}\n{'='*50}")
            artists = self._scrape_artists_from_letter_page(letter)
            if not artists: continue
            if self.max_artists_per_letter and len(artists) > self.max_artists_per_letter:
                artists = artists[:self.max_artists_per_letter]
            results = []
            if self.parallel_workers > 1 and len(artists) > 1:
                results = self._process_artists_parallel(artists, letter)
            else:
                bar = progress.create_bar(f"seq_{letter}", total=len(artists), desc=f"   {letter}", unit="art", position=1)
                for a in artists:
                    s, n, m, nm, im = self._process_single_artist(a)
                    results.append((s, m, nm, im))
                    bar.update(1); bar.set_postfix_str(f"{a['name'][:30]} ({n}mus)", refresh=True)
                bar.close()
            # Totalizadores: cada artista já foi salvo individualmente em _process_single_artist
            letter_a = sum(1 for slug, musics, name_ex, img_ex in results if musics)
            letter_m = sum(len(musics) for slug, musics, name_ex, img_ex in results)
            total_a += letter_a; total_m += letter_m
            progress.write(f"   [OK] {letter}: {letter_a} artistas, {letter_m} musicas")
        progress.write(f"\n{'='*50}\n[DONE] {total_a} artistas, {total_m} musicas\n{'='*50}")

    def run(self):
        logger.info(f"Scraper de artistas (workers={self.parallel_workers})")
        self.scrape_all_artists()
        logger.info("Finalizado!")

if __name__ == "__main__":
    from dotenv import load_dotenv; load_dotenv()
    kw = {}
    for i, a in enumerate(sys.argv[1:]):
        if a == '--limit' and i+1 < len(sys.argv)-1: kw['max_artists_per_letter'] = int(sys.argv[i+2])
        elif a == '--parallel' and i+1 < len(sys.argv)-1: kw['parallel_workers'] = int(sys.argv[i+2])
    PalcoArtistScraper(**kw).run()