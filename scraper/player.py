"""
Módulo de reprodução de áudio.
Permite ouvir músicas diretamente no terminal com playback.
"""

import os
import time
import threading
import subprocess
import sys
from typing import Optional

import requests


class AudioPlayer:
    """
    Player de áudio simples para reproduzir streams do YouTube.
    Suporta play, pause e progresso.
    """

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.is_playing = False
        self.is_paused = False
        self.current_title = ""
        self._stop_event = threading.Event()

    def play_stream(self, stream_url: str, title: str = "Desconhecida") -> None:
        """
        Reproduz um stream de áudio.

        Args:
            stream_url: URL do stream de áudio
            title: Nome da música
        """
        self.stop()
        self.current_title = title
        self._stop_event.clear()

        print(f"\n▶ Reproduzindo: {title}")
        print("  Comandos: [p] pausar/continuar | [s] parar | [q] sair")

        try:
            # Usa ffplay (do ffmpeg) para reprodução se disponível
            if self._has_ffplay():
                self._play_ffplay(stream_url)
            else:
                # Alternativa: salva temporariamente e toca
                self._play_temp_download(stream_url)
        except Exception as e:
            print(f"  ⚠ Erro na reprodução: {e}")
            print("  Tente usar o download e reproduza com seu player favorito.")

    def _has_ffplay(self) -> bool:
        """Verifica se ffplay está disponível."""
        try:
            subprocess.run(
                ["ffplay", "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return True
        except FileNotFoundError:
            return False

    def _play_ffplay(self, stream_url: str) -> None:
        """Reproduz usando ffplay."""
        self.process = subprocess.Popen(
            [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                stream_url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.is_playing = True
        self._monitor_ffplay()

    def _monitor_ffplay(self):
        """Monitora o processo ffplay em background."""
        def monitor():
            while self.process and self.process.poll() is None:
                if self._stop_event.is_set():
                    self.process.terminate()
                    break
                time.sleep(0.5)
            self.is_playing = False
            if not self._stop_event.is_set():
                print(f"\n  ✓ Reprodução finalizada: {self.current_title}")

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()

    def _play_temp_download(self, stream_url: str) -> None:
        """
        Alternativa: tenta abrir o stream no player padrão do sistema
        ou fornece instruções.
        """
        print("\n  ⚠ ffplay não encontrado. Instale ffmpeg para reprodução nativa.")
        print(f"  URL do áudio: {stream_url[:80]}...")
        print("  Você pode usar esta URL em um player como VLC ou mplayer.")

        # Tenta abrir no navegador/player padrão
        if sys.platform == "win32":
            try:
                os.startfile(stream_url)
            except Exception:
                pass

    def pause(self):
        """Pausa/continua a reprodução."""
        if self.process and self.is_playing:
            if not self.is_paused:
                self.process.send_signal(2)  # SIGINT
                self.is_paused = True
                print("  ⏸ Pausado")
            else:
                self.process.send_signal(18)  # SIGCONT
                self.is_paused = False
                print("  ▶ Continuando")

    def stop(self) -> None:
        """Para a reprodução atual."""
        self._stop_event.set()
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
            self.process = None
        self.is_playing = False
        self.is_paused = False