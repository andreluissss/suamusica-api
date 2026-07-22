#!/usr/bin/env python3
"""
YouTube Music Scraper - Interface CLI
Ponto de entrada para executar o scraper no terminal.

Uso:
    python run_cli.py          # Modo interativo
    python run_cli.py --search "Nirvana"  # Busca rápida
"""

import sys
import os

# Adiciona o diretório pai ao path para importar o pacote
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.cli import main

if __name__ == "__main__":
    main()