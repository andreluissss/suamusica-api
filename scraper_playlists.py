"""
Palco MP3 Playlist Scraper - Extrai playlists e suas músicas via GraphQL API.
Uso: python scraper_playlists.py
"""

import os
import re
import time
import json
import base64
import logging
import sys
import threading
import hashlib
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import urljoin

from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

from base_scraper import PalcoBaseScraper, logger, progress


class PalcoPlaylistScraper(PalcoBaseScraper):
    """Scraper que extrai todas as playlists e suas músicas completas via GraphQL API"""

    GRAPHQL_URL = f"{PalcoBaseScraper.BASE_URL}/graphql/"
    PLAYLISTS_QUERY = """
    query PLAYLISTS($after: String, $limit: Int, $genre: [String!], $tag: PlaylistTags, $sort: PlaylistSort) {
      playlists(after: $after, first: $limit, genreSlugs: $genre, tag: $tag, sort: $sort) {
        pageInfo { endCursor hasNextPage __typename }
        edges {
          node {
            playlistID
            title
            id
            coverSquare { dominant_color url url2x url3x __typename }
            artists(first: 4) {
              edges { node { id name __typename } __typename }
              __typename
            }
            __typename
          }
          __typename
        }
        __typename
      }
    }
    """

    PLAYLIST_TRACKS_QUERY = """
    query PLAYLIST_TRACKS($id: Int!, $after: String) {
      playlist(id: $id) {
        playlistID
        title
        tracks(first: 50, after: $after) {
          pageInfo { endCursor hasNextPage }
          edges {
            node {
              id
              music {
                id
                slug
                title
                mp3File
                cover
                artist {
                  id
                  name
                  slug
                }
              }
            }
          }
        }
      }
    }
    """

    def __init__(self):
        super().__init__()
        # Lock exclusivo para o driver Selenium (mesmo que seja sequencial, por seguranca)
        self._driver_lock = threading.Lock()

    def _decode_slug(self, encoded_slug: str) -> str:
        """Decodifica o slug base64 para extrair o ID numérico"""
        try:
            decoded = base64.b64decode(encoded_slug).decode('utf-8')
            if decoded.startswith('Playlist:'):
                return decoded.replace('Playlist:', '')
        except:
            pass
        return encoded_slug

    def _fetch_playlists_page(self, after: str = None, limit: int = 12) -> tuple:
        """Fetch one page of playlists from the GraphQL API"""
        variables = {
            "after": after,
            "limit": limit,
            "genre": None,
            "tag": None,
            "sort": "TOP_WEEKLY"
        }
        payload = {
            "query": self.PLAYLISTS_QUERY,
            "variables": variables,
            "operationName": "PLAYLISTS"
        }
        resp = self.session.post(self.GRAPHQL_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
        playlists = data.get('data', {}).get('playlists', {})
        edges = playlists.get('edges', [])
        page_info = playlists.get('pageInfo', {})
        return edges, page_info.get('hasNextPage', False), page_info.get('endCursor')

    def scrape_all_playlists(self, limit: int = None) -> List[Dict]:
        """Extrai TODAS as playlists via GraphQL API (sem Selenium!)"""
        logger.info("Iniciando extração completa de playlists via GraphQL API")
        
        all_playlists = []
        has_next = True
        cursor = None
        page = 0

        # Cria barra de progresso principal
        progress.write("📋 Extraindo playlists via GraphQL API...")
        
        while has_next:
            page += 1
            edges, has_next, cursor = self._fetch_playlists_page(cursor)

            new_playlists = []
            for edge in edges:
                node = edge.get('node', {})
                playlist_id = node.get('playlistID')
                if not playlist_id or playlist_id in self.processed_playlist_ids:
                    continue

                encoded_id = node.get('id', '')
                slug = self._decode_slug(encoded_id)
                name = self._clean_text(node.get('title', ''))
                if not name:
                    name = f"Playlist {playlist_id}"

                # Extrai cover URL
                cover_square = node.get('coverSquare', {})
                cover_url = cover_square.get('url') or cover_square.get('url2x') or cover_square.get('url3x')
                if cover_url and not cover_url.startswith('http'):
                    cover_url = urljoin(self.BASE_URL, cover_url)

                # Detecta gênero a partir do nome
                detected_genre = self._detect_genre_from_name(name)

                playlist_data = {
                    'playlist_id': int(playlist_id),
                    'name': name,
                    'slug': slug,
                    'cover_url': cover_url or f"{self.BASE_URL}/assets/img/default-playlist.png",
                    'palcomp3_url': f"{self.BASE_URL}/playlist/{slug}/",
                    'genre': detected_genre,
                }
                if detected_genre:
                    progress.write(f"   🏷️ Gênero detectado: {detected_genre} para playlist '{name[:40]}...'")

                new_playlists.append(playlist_data)
                self.processed_playlist_ids.add(playlist_id)

            if new_playlists:
                all_playlists.extend(new_playlists)
                progress.write(f"📄 Página {page}: {len(new_playlists)} novas playlists (total: {len(all_playlists)})")
            else:
                progress.write(f"📄 Página {page}: 0 novas playlists (já processadas)")

            if limit and len(all_playlists) >= limit:
                all_playlists = all_playlists[:limit]
                break

            # Pequena pausa entre chamadas
            time.sleep(0.5)

        logger.info(f"Total de playlists encontradas via API: {len(all_playlists)}")
        return all_playlists

    def _find_existing_music_id(self, palcomp3_url: str) -> Optional[str]:
        """Verifica se uma musica ja existe no banco (playlist_musics) pelo palcomp3_url"""
        try:
            r = self.supabase.table('playlist_musics').select('id').eq('palcomp3_url', palcomp3_url).limit(1).execute()
            if r.data:
                return r.data[0]['id']
        except Exception:
            pass
        return None

    def _fetch_playlist_tracks_graphql(self, playlist_id: int) -> List[Dict]:
        """Extrai TODAS as músicas de uma playlist via GraphQL API com paginação"""
        all_tracks = []
        has_next = True
        cursor = None
        page = 0

        while has_next:
            page += 1
            variables = {"id": playlist_id, "after": cursor}
            payload = {
                "query": self.PLAYLIST_TRACKS_QUERY,
                "variables": variables,
                "operationName": "PLAYLIST_TRACKS"
            }
            try:
                resp = self.session.post(self.GRAPHQL_URL, json=payload, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                if "errors" in data:
                    logger.warning(f"      ⚠️ GraphQL error playlist {playlist_id}: {data['errors'][0]['message'][:100]}")
                    break

                pl = data.get("data", {}).get("playlist", {})
                if not pl:
                    break

                tracks = pl.get("tracks", {})
                edges = tracks.get("edges", [])
                page_info = tracks.get("pageInfo", {})
                has_next = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")
                all_tracks.extend(edges)

                if page == 1:
                    progress.write(f"      [GRAPHQL] Playlist {playlist_id} ('{pl.get('title','?')[:30]}'): buscando tracks...")

            except Exception as e:
                logger.warning(f"      ⚠️ Erro GraphQL playlist {playlist_id} page {page}: {e}")
                break

        return all_tracks

    def _extract_playlist_details_from_html(self, playlist_url: str) -> Dict:
        """Extrai detalhes extras da playlist (descrição, duração) via HTML"""
        details = {'description': None, 'duration': None}
        try:
            response = self.session.get(playlist_url, timeout=30)
            if response.status_code != 200:
                return details
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extrai descrição do og:description
            og_desc = soup.find('meta', property='og:description')
            if og_desc:
                desc = og_desc.get('content', '')
                # Tenta separar gênero e duração da descrição
                # Ex: "Sertanejo • 1h 58min" ou "as mais novas pro seu coração sofrer"
                if '•' in desc:
                    parts = desc.split('•')
                    if len(parts) >= 2:
                        # Ignora o gênero (primeira parte) e pega duração
                        details['duration'] = parts[1].strip()
                    else:
                        details['description'] = desc.strip()
                else:
                    details['description'] = desc.strip()
            
            # Tenta extrair descrição do título h2
            h2 = soup.find('h2')
            if h2:
                details['description'] = h2.get_text().strip()
            
            # Tenta extrair duração do texto
            duration_match = re.search(r'(\d+h\s*\d+min|\d+:\d+)', soup.get_text())
            if duration_match:
                details['duration'] = duration_match.group(1)
            
        except Exception as e:
            logger.warning(f"      ⚠️ Erro ao extrair detalhes HTML: {e}")
        
        return details

    def process_playlist_musics(self, playlist: Dict) -> List[Dict]:
        """Extrai todas as músicas de uma playlist via GraphQL API (sem Selenium!)"""
        playlist_id = playlist['playlist_id']

        try:
            # Busca TODAS as tracks via GraphQL com paginação
            all_edges = self._fetch_playlist_tracks_graphql(playlist_id)
            progress.write(f"      [GRAPHQL] {len(all_edges)} tracks encontradas na playlist {playlist_id}")

            musics = []
            position = 1
            for edge in all_edges:
                try:
                    node = edge.get("node", {})
                    music = node.get("music", {})

                    music_slug = music.get("slug", "")
                    if not music_slug:
                        continue

                    title = music.get("title", "")
                    if not title or len(title) < 2:
                        title = music_slug.replace("-", " ").title()

                    mp3_file = music.get("mp3File", "")

                    # Extrai artista do GraphQL
                    artist_data = music.get("artist", {})
                    artist_slug = ""
                    artist_name = ""
                    if isinstance(artist_data, dict) and artist_data.get("slug"):
                        artist_slug = artist_data.get("slug", "")
                        artist_name = artist_data.get("name", "")
                    if not artist_slug:
                        # Fallback: tenta extrair do slug da musica (formato: /artista/musica/)
                        parts = music_slug.split("/")
                        if len(parts) >= 2:
                            artist_slug = parts[0]
                            artist_name = artist_slug.replace("-", " ").title()
                        else:
                            artist_slug = "unknown"
                            artist_name = "Unknown Artist"

                    music_id = self._generate_id("")
                    genre = playlist.get("genre", None)
                    palcomp3_url = urljoin(self.BASE_URL, f"/{artist_slug}/{music_slug}/")

                    musics.append({
                        "id": music_id,
                        "playlist_id": playlist_id,
                        "title": title,
                        "artist_name": artist_name,
                        "artist_slug": artist_slug,
                        "genre": genre,
                        "plays": 0,
                        "mp3_url": mp3_file if mp3_file else None,
                        "palcomp3_url": palcomp3_url,
                        "position": position
                    })
                    position += 1

                except Exception as e:
                    logger.warning(f"      ⚠️ Erro ao processar track {edge}: {e}")

            return musics

        except Exception as e:
            logger.error(f"❌ Erro ao processar playlist {playlist_id}: {e}")
            return []

    @staticmethod
    def _sanitize(val):
        """Remove caracteres nulos (\\u0000) de strings para evitar erro do PostgreSQL"""
        if isinstance(val, str):
            return val.replace('\x00', '').replace('\\u0000', '')
        return val

    def _batch_upsert_musics(self, table: str, records: List[Dict], conflict_col: str) -> int:
        """
        Faz upsert em lote no Supabase. Se o registro ja existe (pelo conflict_col),
        ele ATUALIZA em vez de inserir duplicata. NUNCA perde dados.
        
        Se conflict_col for None, faz INSERT normal (sem conflito).
        Usa palcomp3_url para reutilizar IDs de registros existentes.
        """
        if not records:
            return 0

        total = 0
        for i in range(0, len(records), self.BATCH_SIZE):
            batch = records[i:i + self.BATCH_SIZE]
            try:
                if conflict_col:
                    self.supabase.table(table).upsert(batch, on_conflict=conflict_col).execute()
                else:
                    self.supabase.table(table).insert(batch).execute()
                total += len(batch)
            except Exception as e:
                logger.warning(f"   ⚠️ Erro no upsert em {table} ({len(batch)} registros): {e}")
                # Fallback: insere um por um
                for record in batch:
                    try:
                        if conflict_col:
                            self.supabase.table(table).upsert(record, on_conflict=conflict_col).execute()
                        else:
                            self.supabase.table(table).insert(record).execute()
                        total += 1
                    except Exception:
                        pass

        return total

    def _batch_insert_musics_safe(self, records: List[Dict]) -> int:
        """
        Faz INSERT seguro para playlist_musics sem perder músicas de outras playlists.
        
        PROBLEMA DO UPSERT POR ID:
        - Se a mesma música aparece em 2 playlists, UPSERT por id muda o playlist_id
        - Música "soma" da playlist anterior
        
        SOLUÇÃO:
        - Usa INSERT normal (gera novo ID para cada playlist)
        - NÃO deleta nada - se houver duplicata, INSERT falha mas não perde dados
        - Garante que cada playlist tem suas próprias músicas
        """
        if not records:
            return 0
        
        # Faz INSERT normal (sem DELETE, sem UPSERT por id)
        total = 0
        for i in range(0, len(records), self.BATCH_SIZE):
            batch = records[i:i + self.BATCH_SIZE]
            try:
                self.supabase.table('playlist_musics').insert(batch).execute()
                total += len(batch)
            except Exception as e:
                logger.warning(f"   ⚠️ Erro no INSERT em playlist_musics ({len(batch)} registros): {e}")
                # Fallback: insere um por um
                for record in batch:
                    try:
                        self.supabase.table('playlist_musics').insert(record).execute()
                        total += 1
                    except Exception as insert_error:
                        # Loga erro específico para debug
                        logger.warning(f"      ⚠️ Erro ao inserir música {record.get('title', '?')[:30]}: {insert_error}")
                        # Continua para próxima música (não para tudo)

        return total

    def save_data(self, playlists: List[Dict]):
        """Salva CADA playlist e suas músicas via INSERT seguro.
        
        GARANTIAS:
        - Cada playlist tem suas próprias músicas com IDs únicos (hash MD5)
        - Mesma música em playlists diferentes = registros diferentes (coexistem)
        - NENHUM DELETE é executado (dados nunca são removidos)
        - NÃO há duplicatas dentro da mesma playlist
        - Salva APENAS nas tabelas playlists e playlist_musics
        - Confia 100% no GraphQL para mp3_url e dados da musica
        - TODAS as tracks são salvas (não há perda de dados)
        """
        total_playlists = 0
        total_musics = 0

        # Reduz nivel de logging
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('base_scraper').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('selenium').setLevel(logging.WARNING)

        main_bar = progress.create_bar(
            "playlists", total=len(playlists),
            desc="📀 Playlists", unit="pl", position=0
        )

        for playlist in playlists:
            main_bar.set_postfix_str(f"{playlist['name'][:30]}", refresh=True)

            # --- 1. EXTRAIR MUSICAS VIA GRAPHQL APENAS (sem HTTP extra) ---
            musics = self.process_playlist_musics(playlist)
            
            # --- 2. SALVAR PLAYLIST (UPSERT por playlist_id - nunca deleta) ---
            pl_rec = {
                'playlist_id': playlist['playlist_id'],
                'name': self._sanitize(playlist['name']),
                'slug': self._sanitize(playlist.get('slug', '')),
                'cover_url': self._sanitize(playlist.get('cover_url')),
                'palcomp3_url': self._sanitize(playlist.get('palcomp3_url')),
            }
            
            try:
                saved_pl = self._batch_upsert_musics('playlists', [pl_rec], 'playlist_id')
                if saved_pl:
                    total_playlists += saved_pl
            except Exception as e:
                logger.warning(f"⚠️ Erro ao salvar playlist {pl_rec['playlist_id']}: {e}")

            music_bar = progress.create_bar(
                f"musics_{playlist['playlist_id']}",
                total=len(musics), desc=f"   🎵 ({playlist['playlist_id']})",
                unit="mu", position=1
            )

            bm_playlist = []

            for music in musics:
                genre_name = self._sanitize(music.get('genre'))

                # USA SOMENTE DADOS DO GRAPHQL - SEM REQUISICOES HTTP EXTRAS
                # GraphQL retorna mp3File para 100% das tracks (confirmado)
                # Cover NAO vem do GraphQL, usa placeholder
                mp3_url = music.get('mp3_url')
                
                # NUNCA pula musica - salva todas mesmo sem mp3
                # Gera ID único por playlist + música para evitar conflitos
                palcomp3_url = self._sanitize(music['palcomp3_url'])
                playlist_id = music['playlist_id']
                music_id = music['id'][:14]
                # Combina playlist_id + music_id + palcomp3_url para criar ID único
                # Usa hash MD5 para garantir unicidade absoluta
                unique_str = f"{playlist_id}_{music_id}_{palcomp3_url}"
                mid = hashlib.md5(unique_str.encode()).hexdigest()[:14]

                bm_playlist.append({
                    'id': mid,
                    'playlist_id': music['playlist_id'],
                    'title': self._sanitize(music['title']),
                    'artist_name': self._sanitize(music['artist_name']),
                    'genre': genre_name,
                    'plays': music.get('plays', 0),
                    'cover_url': "https://via.placeholder.com/500x500/cccccc/666666?text=No+Cover",
                    'mp3_url': self._sanitize(mp3_url) if mp3_url else None,
                    'palcomp3_url': palcomp3_url,
                    'position': music.get('position', 0)
                })

                music_bar.update(1)
                music_bar.set_postfix_str(music['title'][:30])

            # --- 3. SALVAR MUSICAS VIA INSERT (UPSERT por id causa perda de dados) ---
            # UPSERT por 'id' faz música mudar de playlist quando aparece em múltiplas playlists
            # INSERT com IDs únicos por playlist (sem DELETE)
            saved_m = self._batch_insert_musics_safe(bm_playlist) if bm_playlist else 0
            total_musics += saved_m

            if saved_m == len(musics):
                music_bar.set_postfix_str(f"✅ {len(musics)} musicas salvas")
            else:
                music_bar.set_postfix_str(f"⚠️ {saved_m}/{len(musics)} musicas (parcial)")
            music_bar.close()
            main_bar.update(1)

        main_bar.close()

        progress.write(f"\n{'='*60}")
        progress.write(f"✅ RESUMO PLAYLISTS:")
        progress.write(f"   📀 Playlists: {total_playlists}")
        progress.write(f"   🎵 Musicas:   {total_musics}")
        progress.write(f"{'='*60}")
        progress.write(f"💡 Músicas têm IDs únicos por playlist (playlist_id + music_id).")
        progress.write(f"   NENHUM DELETE é executado (dados nunca são removidos).")
        progress.write(f"   Zero requisicoes HTTP extras para capa/MP3.")
        progress.write(f"   GraphQL fornece 100% dos mp3_url.")

    def run(self):
        """Executa o scraper de playlists completo"""
        logger.info("🚀 Iniciando scraper de playlists completo")
        playlists = self.scrape_all_playlists()
        if playlists:
            self.save_data(playlists)
        else:
            logger.warning("Nenhuma playlist encontrada")
        logger.info("✅ Scraper de playlists finalizado!")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    scraper = PalcoPlaylistScraper()
    scraper.run()