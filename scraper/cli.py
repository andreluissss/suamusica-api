"""
Interface de Linha de Comando (CLI).
Fluxo simplificado: busca → resultados com ações inline [P]lay [D]ownload [T]racks.
"""

import os
import sys
from typing import List, Dict

from .scraper import YouTubeScraper
from .player import AudioPlayer


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner():
    banner = """
╔══════════════════════════════════════════════════════════╗
║                 🎵 YouTube Music Scraper 🎵              ║
║        Busque → Escolha → Play ou Download              ║
╚══════════════════════════════════════════════════════════╝
"""
    print(banner)


def show_results(results: List[Dict]):
    """Exibe resultados formatados."""
    print(scraper_module.YouTubeScraper.format_results(results))


def run_cli():
    scraper = YouTubeScraper()
    player = AudioPlayer()
    last_results: List[Dict] = []
    current_tracks: List[Dict] = []
    playlist_title = ""

    clear_screen()
    print_banner()
    print(f"📁 Downloads salvos em: {scraper.download_dir}")

    while True:
        # ── MODO BUSCA ──
        query = input("\n🎤 Pesquisar artista/música/playlist (ou 'sair'): ").strip()
        if query.lower() in ("sair", "0", "q", "exit"):
            print("\n👋 Até logo!\n")
            player.stop()
            break

        if not query:
            continue

        clear_screen()
        print_banner()
        print(f"🔍 Buscando por: '{query}'...\n")

        try:
            results = scraper.search(query)
            last_results = results
            current_tracks = []
            playlist_title = ""
            print(scraper.format_results(results))
        except Exception as e:
            print(f"  ❌ Erro na busca: {e}")
            continue

        if not results:
            print("  Nenhum resultado encontrado.")
            continue

        # ── MODO AÇÃO ──
        while True:
            action = input("\n👉 Ação (ex: 1p, 2d, 3t, ou 'nova' busca): ").strip().lower()

            if action in ("nova", "n", "back", "b"):
                clear_screen()
                print_banner()
                break

            if action in ("sair", "0", "q"):
                print("\n👋 Até logo!\n")
                player.stop()
                return

            # ── Se está visualizando tracks de uma playlist ──
            if current_tracks and action.isdigit():
                idx = int(action)
                if 1 <= idx <= len(current_tracks):
                    track = current_tracks[idx - 1]
                    sub = input(f"  [{track['title']}] [P]lay ou [D]ownload: ").strip().lower()
                    if sub == "p":
                        try:
                            stream_url, title = scraper.get_audio_stream_url(track["url"])
                            player.play_stream(stream_url, title)
                        except Exception as e:
                            print(f"  ❌ Erro: {e}")
                    elif sub == "d":
                        try:
                            fname = f"{track['channel']} - {track['title']}"[:80]
                            filepath = scraper.download_audio(track["url"], filename=fname)
                            print(f"  ✅ Baixado: {filepath}")
                        except Exception as e:
                            print(f"  ❌ Erro: {e}")
                    continue

            # ── Parse ação nos resultados principais ──
            if len(action) < 2:
                print("  ⚠ Use formato: NÚMERO + LETRA (ex: 1p, 2d)")
                continue

            num_str = action[:-1]
            cmd = action[-1]

            if not num_str.isdigit():
                print("  ⚠ Use formato: NÚMERO + LETRA (ex: 1p, 2d)")
                continue

            idx = int(num_str)
            if idx < 1 or idx > len(last_results):
                print("  ⚠ Número fora do intervalo.")
                continue

            item = last_results[idx - 1]
            item_type = item.get("type", "video")

            # ── Comando: Play ──
            if cmd == "p":
                if item_type not in ("video", "track"):
                    print("  ⚠ Apenas músicas podem ser reproduzidas. Use [T] para ver faixas da playlist.")
                    continue
                try:
                    stream_url, title = scraper.get_audio_stream_url(item["url"])
                    player.play_stream(stream_url, title)
                except Exception as e:
                    print(f"  ❌ Erro ao reproduzir: {e}")

            # ── Comando: Download ──
            elif cmd == "d":
                if item_type not in ("video", "track"):
                    print("  ⚠ Apenas músicas podem ser baixadas. Use [DP] para baixar playlist toda.")
                    continue
                try:
                    print(f"\n  ⬇ Baixando: {item['title']}...")
                    fname = f"{item['channel']} - {item['title']}"[:80]
                    filepath = scraper.download_audio(item["url"], filename=fname)
                    print(f"  ✅ OK! Salvo em: {filepath}")
                except Exception as e:
                    print(f"  ❌ Erro no download: {e}")

            # ── Comando: Tracks (ver faixas da playlist) ──
            elif cmd == "t":
                if item_type != "playlist":
                    print("  ⚠ Apenas playlists têm faixas para listar.")
                    continue
                try:
                    print(f"\n  📋 Carregando faixas da playlist: {item['title']}...")
                    tracks = scraper.get_playlist_tracks(item["url"])
                    current_tracks = tracks
                    playlist_title = item["title"]
                    clear_screen()
                    print_banner()
                    print(f"📋 PLAYLIST: {playlist_title} ({len(tracks)} músicas)")
                    print(scraper.format_results(tracks))
                    print("\nDigite o NÚMERO para selecionar faixa, ou 'back' para voltar")
                except Exception as e:
                    print(f"  ❌ Erro ao carregar faixas: {e}")

            # ── Comando: Download Playlist ──
            elif cmd == "dp" or action.endswith("dp"):
                if item_type != "playlist":
                    print("  ⚠ Apenas playlists podem ser baixadas inteiras.")
                    continue
                try:
                    print(f"\n  ⬇⬇ Baixando playlist: {item['title']}...")
                    # Usa progress_callback para feedback visual
                    def progress_callback(status):
                        if status["status"] == "downloading":
                            print(f"  ⬇ [{status['index']}/{status['total']}] {status['track']}...")
                        elif status["status"] == "completed":
                            print(f"  ✅ [{status['index']}/{status['total']}] {status['track']}")
                        elif status["status"] == "failed":
                            print(f"  ❌ [{status['index']}/{status['total']}] {status['track']}: {status['error']}")

                    files = scraper.download_playlist_audios(
                        item["url"],
                        max_concurrent=3,
                        progress_callback=progress_callback
                    )
                    print(f"\n  ✅ Playlist baixada! {len(files)} música(s) salva(s).")
                except Exception as e:
                    print(f"  ❌ Erro: {e}")

            else:
                print("  ⚠ Comando inválido. Use: [P]lay [D]ownload [T]racks [DP] Download Playlist")


def main():
    global scraper_module
    from . import scraper as scraper_module

    try:
        run_cli()
    except KeyboardInterrupt:
        print("\n\n👋 Até logo!\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()