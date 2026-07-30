#!/usr/bin/env bash
# Build script para Render - Instala FFmpeg necessário para yt-dlp

# Instala FFmpeg
apt-get update && apt-get install -y ffmpeg

# Instala dependências Python
pip install -r requirements.txt
