FROM python:3.12-slim

WORKDIR /app

# Instala ffmpeg (necessário para yt-dlp processar áudio)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copia os arquivos do projeto
COPY scraper/ ./scraper/
COPY railway.json ./
COPY .gitignore ./

# Instala as dependências
RUN pip install --no-cache-dir -r scraper/requirements.txt

# Torna o entrypoint executável
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Porta que o Flask vai rodar
EXPOSE 5000

# Define o caminho do arquivo de cookies para autenticação no YouTube
ENV YOUTUBE_COOKIES_FILE=/app/scraper/cookies.txt

# Comando para iniciar o servidor via entrypoint
CMD ["/app/entrypoint.sh"]
