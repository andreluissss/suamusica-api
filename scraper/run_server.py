#!/usr/bin/env python3
"""
YouTube Music Scraper - Servidor API
Ponto de entrada para executar o servidor Flask.

Uso:
    python run_server.py                    # Porta 5000
    python run_server.py --port 8080        # Porta personalizada
    python run_server.py --debug            # Modo debug
"""

import sys
import os

# Adiciona o diretório pai ao path para importar o pacote
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.server import main

if __name__ == "__main__":
    main()