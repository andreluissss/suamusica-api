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

# Porta que o Flask vai rodar
EXPOSE 5000

# Comando para iniciar o servidor
CMD ["python", "scraper/run_server.py", "--host", "0.0.0.0", "--port", "5000"]