"""
Palco MP3 Podcast Scraper - Extrai podcasts e seus episódios via GraphQL API.
Extrai de TODAS as categorias/gêneros disponíveis.

Uso: python scraper_podcasts.py
      python scraper_podcasts.py --limit 10
      python scraper_podcasts.py --genre-only  (só lista categorias, não extrai)
"""

import os
import re
import time
import json
import base64
import logging
import sys
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin

from base_scraper import PalcoBaseScraper, logger, progress


class PalcoPodcastScraper(PalcoBaseScraper):
    """
    Scraper que extrai podcasts do Palco MP3 via GraphQL API.

    Endpoint: https://www.palcomp3.com.br/graphql/
    """

    GRAPHQL_URL = f"{PalcoBaseScraper.BASE_URL}/graphql/"

    GENRES_QUERY = """
    query PodcastGenres {
      podcastGenres(first: 200) {
        nodes {
          id
          name
        }
      }
    }
    """

    HIGHLIGHTS_QUERY = """
    query PodcastHighlights($first: Int, $genres: [Int!], $after: String) {
      podcastHighlights(first: $first, genres: $genres, after: $after) {
        total
        pageInfo {
          endCursor
          hasNextPage
        }
        nodes {
          id
          podcastID
          title
          author
          summary
          image
        }
      }
    }
    """

    PODCAST_EPISODES_QUERY = """
    query GetPodcastEpisodes($id: Int!, $after: String) {
      podcast(id: $id) {
        id
        podcastID
        title
        author
        summary
        image
        episodes(first: 100, after: $after) {
          total
          pageInfo {
            endCursor
            hasNextPage
          }
          nodes {
            id
            episodeID
            title
            description
            image
            duration
            publicationDate
            mediaURL
          }
        }
      }
    }
    """

    def __init__(self, max_podcasts: int = None):
        super().__init__()
        self.max_podcasts = max_podcasts
        self.processed_podcast_ids: Set[int] = set()

    def _graphql_request(self, query: str, variables: dict = None) -> dict:
        """Faz uma requisição GraphQL e retorna os dados"""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = self.session.post(self.GRAPHQL_URL, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _extract_numeric_id(self, base64_id: str) -> int:
        """Extrai o ID numérico de um ID codificado em base64 (ex: PodcastGenre:1303 -> 1303)"""
        try:
            decoded = base64.b64decode(base64_id).decode('utf-8')
            return int(decoded.split(':')[1])
        except Exception:
            return 0

    def fetch_all_genres(self) -> List[Dict]:
        """Busca todos os gêneros/categorias de podcast com seus IDs numéricos"""
        progress.write("📂 Buscando categorias de podcasts...")
        data = self._graphql_request(self.GENRES_QUERY)
        genres = data.get('data', {}).get('podcastGenres', {}).get('nodes', [])
        
        result = []
        for g in genres:
            numeric_id = self._extract_numeric_id(g['id'])
            result.append({
                'id': g['id'],
                'numeric_id': numeric_id,
                'name': g['name'],
            })
        
        progress.write(f"   📊 {len(result)} categorias encontradas")
        for g in result:
            progress.write(f"      - {g['name']} (ID: {g['numeric_id']})")
        return result

    def fetch_podcasts_by_genre(self, genre_numeric_id: int = None, genre_name: str = None) -> List[Dict]:
        """
        Busca TODOS os podcasts de um gênero específico (ou todos se genre_numeric_id=None).
        Usa paginação para pegar TODOS os podcasts.
        """
        label = f"gênero '{genre_name}'" if genre_name else "todos os gêneros"
        progress.write(f"   🔍 Buscando podcasts de {label}...")

        all_podcasts = []
        cursor = None
        has_next = True
        page = 0

        while has_next:
            page += 1
            variables = {
                "first": 100,
                "after": cursor,
            }
            if genre_numeric_id:
                variables["genres"] = [genre_numeric_id]

            try:
                data = self._graphql_request(self.HIGHLIGHTS_QUERY, variables)
                highlights = data.get('data', {}).get('podcastHighlights', {})
                nodes = highlights.get('nodes', [])
                page_info = highlights.get('pageInfo', {})

                new_podcasts = []
                for node in nodes:
                    podcast_id = node.get('podcastID')
                    if not podcast_id or podcast_id in self.processed_podcast_ids:
                        continue

                    podcast_data = {
                        'id': str(podcast_id),
                        'podcast_id': podcast_id,
                        'name': node.get('title', ''),
                        'author': node.get('author', ''),
                        'summary': node.get('summary', ''),
                        'cover_url': node.get('image', ''),
                        'genre': genre_name,
                        'graphql_id': node.get('id', ''),
                    }
                    new_podcasts.append(podcast_data)
                    self.processed_podcast_ids.add(podcast_id)

                all_podcasts.extend(new_podcasts)
                progress.write(f"      Página {page}: +{len(new_podcasts)} podcasts (total acumulado: {len(all_podcasts)})")

                has_next = page_info.get('hasNextPage', False)
                cursor = page_info.get('endCursor')

                if self.max_podcasts and len(all_podcasts) >= self.max_podcasts:
                    all_podcasts = all_podcasts[:self.max_podcasts]
                    break

                time.sleep(0.3)

            except Exception as e:
                progress.write(f"      ❌ Erro na página {page}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    progress.write(f"      Response: {e.response.text[:500]}")
                break

        return all_podcasts

    def fetch_podcast_episodes(self, podcast_id: int) -> List[Dict]:
        """
        Busca TODOS os episódios de um podcast usando paginação.
        """
        all_episodes = []
        cursor = None
        has_next = True
        page = 0

        while has_next:
            page += 1
            variables = {"id": podcast_id, "after": cursor}

            try:
                data = self._graphql_request(self.PODCAST_EPISODES_QUERY, variables)
                podcast_data = data.get('data', {}).get('podcast', {})
                if not podcast_data:
                    progress.write(f"      ⚠️ Podcast não encontrado na API (ID: {podcast_id})")
                    break

                episodes_data = podcast_data.get('episodes', {})
                total_episodes = episodes_data.get('total', 0)
                nodes = episodes_data.get('nodes', [])
                page_info = episodes_data.get('pageInfo', {})

                for node in nodes:
                    episode_id = node.get('episodeID')
                    if not episode_id:
                        continue

                    episode_data = {
                        'id': episode_id,
                        'episode_id': episode_id,
                        'podcast_id': podcast_id,
                        'title': node.get('title', ''),
                        'description': node.get('description', ''),
                        'cover_url': node.get('image', ''),
                        'duration': node.get('duration'),
                        'published_at': node.get('publicationDate'),
                        'audio_url': node.get('mediaURL'),
                    }
                    all_episodes.append(episode_data)

                progress.write(f"      Página {page}: +{len(nodes)} eps (total: {len(all_episodes)}/{total_episodes})")

                has_next = page_info.get('hasNextPage', False)
                cursor = page_info.get('endCursor')
                time.sleep(0.2)

            except Exception as e:
                progress.write(f"      ❌ Erro ao buscar episódios (página {page}): {e}")
                break

        return all_episodes

    def scrape_all_podcasts(self) -> List[Dict]:
        """
        Extrai TODOS os podcasts de TODAS as categorias via GraphQL API.
        """
        progress.write("🎙️ Iniciando extração completa de podcasts via GraphQL API")

        # 1. Busca todas as categorias
        genres = self.fetch_all_genres()

        # 2. Primeiro busca sem filtro (retorna os 78 podcasts em destaque)
        progress.write("\n📦 Buscando podcasts em destaque (todas as categorias)...")
        all_podcasts = self.fetch_podcasts_by_genre(genre_name="Destaques")

        # 3. Depois busca por cada gênero específico para garantir cobertura total
        progress.write("\n📦 Buscando podcasts por categoria...")
        for genre in genres:
            if self.max_podcasts and len(all_podcasts) >= self.max_podcasts:
                break
            
            genre_podcasts = self.fetch_podcasts_by_genre(
                genre_numeric_id=genre['numeric_id'],
                genre_name=genre['name']
            )
            all_podcasts.extend(genre_podcasts)

            if self.max_podcasts and len(all_podcasts) >= self.max_podcasts:
                all_podcasts = all_podcasts[:self.max_podcasts]
                break

        # Remove duplicatas mantendo a ordem
        seen = set()
        unique_podcasts = []
        for p in all_podcasts:
            if p['podcast_id'] not in seen:
                seen.add(p['podcast_id'])
                unique_podcasts.append(p)

        progress.write(f"\n🎯 Total de podcasts únicos encontrados: {len(unique_podcasts)}")
        return unique_podcasts

    def save_data(self, podcasts: List[Dict]):
        """
        Salva todos os podcasts e episódios no Supabase usando BATCH para máxima performance.

        Tabelas:
          - podcasts:        id(string PK), podcast_id(integer), title, slug, host_name, host_slug,
                             description, cover_url, episode_count, palcomp3_url, created_at, updated_at
          - podcast_episodes: id(string PK), episode_id(integer), podcast_id(string FK), podcast_id_ref(integer FK),
                             title, slug, description, duration, plays(integer), published_at, audio_url,
                             cover_url, palcomp3_url, created_at, updated_at
        """
        total_podcasts = 0
        total_episodes = 0

        # Reduz nível de logging para não interferir com barra de progresso
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('base_scraper').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)

        # Cria barra de progresso principal - NUNCA desaparece
        main_bar = progress.create_bar(
            "podcasts",
            total=len(podcasts),
            desc="🎙️ Podcasts",
            unit="pod",
            position=0
        )

        # Acumuladores para batch insert
        all_podcast_records = []
        all_episode_records = []
        podcast_episode_counts = {}  # podcast_id -> episode_count

        for podcast in podcasts:
            main_bar.set_postfix_str(f"{podcast['name'][:30]}", refresh=True)
            podcast_id = podcast['podcast_id']

            # Gera slug
            slug = podcast['name'].lower().replace(' ', '-').replace('--', '-')[:50]
            palcomp3_url = f"{self.BASE_URL}/podcast/{podcast_id}/"

            # Prepara registro do podcast
            all_podcast_records.append({
                'id': str(podcast_id),
                'podcast_id': podcast_id,
                'title': podcast['name'],
                'slug': slug,
                'host_name': podcast.get('author', ''),
                'host_slug': podcast.get('author', '').lower().replace(' ', '-')[:50],
                'description': podcast.get('summary', ''),
                'cover_url': podcast.get('cover_url', ''),
                'episode_count': 0,
                'palcomp3_url': palcomp3_url,
            })

            # Busca episódios
            progress.write(f"   🎧 Buscando episódios de: {podcast['name']}...")
            episodes = self.fetch_podcast_episodes(podcast_id)
            progress.write(f"      📊 {len(episodes)} episódios encontrados")

            # Prepara registros de episódios
            episode_count = 0
            for episode in episodes:
                episode_id = episode['episode_id']
                episode_id_str = f"ep_{episode_id}_{podcast_id}"

                # Só salva se tiver audio_url válido
                audio_url = episode.get('audio_url')
                if not audio_url:
                    progress.write(f"      ⚠️ Pulando episódio sem áudio: {episode['title'][:50]}...")
                    continue

                # Gera slug do episódio
                ep_slug = episode['title'].lower().replace(' ', '-').replace('--', '-')[:100] if episode['title'] else f"episode-{episode_id}"
                palcomp3_ep_url = f"{self.BASE_URL}/podcast/{podcast_id}/{episode_id}/" if episode_id else None

                all_episode_records.append({
                    'id': episode_id_str,
                    'episode_id': int(episode_id),
                    'podcast_id': str(podcast_id),
                    'podcast_id_ref': podcast_id,
                    'title': episode['title'],
                    'slug': ep_slug,
                    'description': episode.get('description', ''),
                    'cover_url': episode.get('cover_url', ''),
                    'duration': episode.get('duration'),
                    'published_at': episode.get('published_at'),
                    'audio_url': audio_url,
                    'palcomp3_url': palcomp3_ep_url,
                })
                episode_count += 1

            podcast_episode_counts[podcast_id] = episode_count
            main_bar.update(1)

        main_bar.close()
        
        progress.write("\n" + "="*60)
        progress.write("💾 SALVANDO DADOS NO SERVIDOR (BATCH)...")
        progress.write("="*60)

        # --- Batch insert: Podcasts ---
        if all_podcast_records:
            saved = self._batch_insert('podcasts', all_podcast_records, 'id')
            total_podcasts = saved
            progress.write(f"🎙️ Podcasts salvos: {saved}")

        # --- Batch insert: Episódios ---
        if all_episode_records:
            saved = self._batch_insert('podcast_episodes', all_episode_records, 'id')
            total_episodes = saved
            progress.write(f"🎧 Episódios salvos: {saved}")

        # --- Atualiza episode_count nos podcasts (individual, são poucos) ---
        for podcast_id, count in podcast_episode_counts.items():
            try:
                self.supabase.table('podcasts').update({
                    'episode_count': count
                }).eq('id', str(podcast_id)).execute()
            except Exception as e:
                logger.warning(f"   ⚠️ Erro ao atualizar episode_count do podcast {podcast_id}: {e}")

        progress.write(f"\n{'='*60}")
        progress.write(f"✅ RESUMO PODCASTS:")
        progress.write(f"   🎙️ Podcasts:  {total_podcasts}")
        progress.write(f"   🎧 Episódios: {total_episodes}")
        progress.write(f"{'='*60}")

    def run(self):
        """Executa o scraper de podcasts completo"""
        logger.info("🎙️ Iniciando scraper de podcasts")
        podcasts = self.scrape_all_podcasts()
        if podcasts:
            self.save_data(podcasts)
        else:
            logger.warning("Nenhum podcast encontrado")
        logger.info("🎙️ Scraper de podcasts finalizado!")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    import sys

    kwargs = {}
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == '--limit' and i + 1 < len(args):
            kwargs['max_podcasts'] = int(args[i + 1])

    scraper = PalcoPodcastScraper(**kwargs)
    scraper.run()