# Dockerfile para YouTube Media Processor API
# Baseado em Python 3.11 com FFmpeg para processamento de áudio
# Otimizado para deploy no Render via Docker

FROM python:3.11-slim

# Define labels para metadados
LABEL maintainer="your-email@example.com"
LABEL description="API para scraping e processamento de mídia do YouTube"
LABEL version="2.0.0"

# Atualiza pacotes e instala FFmpeg e dependências necessárias
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Define diretório de trabalho
WORKDIR /app

# Copia arquivo de requirements
COPY requirements.txt .

# Instala dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Instala dependências extras para os scrapers
RUN pip install --no-cache-dir beautifulsoup4 requests supabase

# Copia todos os arquivos da aplicação
COPY main.py .
COPY service.py .
COPY schemas.py .
COPY jamendo.py .
COPY scrapernovo.py .

# Cria diretório para downloads
RUN mkdir -p /app/downloads

# Expõe porta 8000
EXPOSE 8000

# Define variáveis de ambiente padrão
ENV HOST=0.0.0.0
ENV PORT=8000
ENV DOWNLOAD_DIR=/app/downloads

# Comando para rodar a aplicação
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]