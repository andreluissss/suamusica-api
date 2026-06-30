# YouTube Media Processor API

API RESTful para scraping e processamento de mídia do YouTube, desenvolvida com FastAPI e yt-dlp.

## Funcionalidades

- **Busca de vídeos**: Pesquisa por artista, música, playlist ou link direto
- **Download de áudio**: Conversão para MP3 em alta qualidade (320kbps, 192kbps, 128kbps)
- **Streaming**: Opção para streaming direto sem download completo
- **Assíncrono**: Processamento não-bloqueante com asyncio

## Tecnologias

- **FastAPI**: Framework web moderno e rápido
- **yt-dlp**: Biblioteca robusta para extração de metadados do YouTube
- **FFmpeg**: Conversão de vídeo para áudio
- **Docker**: Containerização da aplicação
- **Pydantic**: Validação de dados

## Estrutura do Projeto

```
.
├── main.py              # Aplicação FastAPI com endpoints
├── service.py           # Lógica de integração com yt-dlp
├── schemas.py           # Modelos Pydantic para validação
├── requirements.txt     # Dependências Python
├── Dockerfile           # Configuração do container Docker
├── docker-compose.yml   # Orquestração de serviços
├── render.yaml          # Configuração para Render
├── railway.json         # Configuração para Railway
├── Procfile             # Configuração para Heroku-style
├── .env.example         # Exemplo de variáveis de ambiente
└── README.md            # Documentação
```

## Instalação Local

### Pré-requisitos

- Python 3.11+
- FFmpeg instalado no sistema
- pip

### Passos

1. Clone o repositório:
```bash
git clone <repository-url>
cd sp
```

2. Crie o ambiente virtual:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. Instale as dependências:
```bash
pip install -r requirements.txt
```

4. Configure as variáveis de ambiente (opcional):
```bash
cp .env.example .env
```

5. Execute a aplicação:
```bash
python main.py
```

A API estará disponível em `http://localhost:8000`

## Instalação com Docker

### Pré-requisitos

- Docker
- Docker Compose

### Passos

1. Configure as variáveis de ambiente (opcional):
```bash
cp .env.example .env
```

2. Construa e execute os containers:
```bash
docker-compose up -d --build
```

A API estará disponível em `http://localhost:8000`

3. Para parar os containers:
```bash
docker-compose down
```

## Deploy na Nuvem

### Render (Recomendado - Plano Free)

Render oferece um plano gratuito com suporte a Python e disco persistente.

1. Crie uma conta em [render.com](https://render.com)
2. Faça fork do repositório ou conecte seu GitHub
3. Crie um novo "Web Service"
4. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Environment Variables**:
     - `PORT`: `8000`
     - `DOWNLOAD_DIR`: `/opt/render/project/src/downloads`
5. Adicione um disco persistente de 1GB para downloads
6. Deploy automático ao fazer push no GitHub

### Railway (Plano Free)

Railway é outra opção com plano gratuito e deploy automático.

1. Crie uma conta em [railway.app](https://railway.app)
2. Crie um novo projeto e conecte seu repositório
3. Railway detectará automaticamente a configuração do `railway.json`
4. Configure as variáveis de ambiente:
   - `PORT`: `8000`
   - `DOWNLOAD_DIR`: `/app/downloads`
5. Deploy automático ao fazer push no GitHub

### Heroku (Requer Cartão de Crédito)

Heroku oferece suporte a Python com o Procfile incluído.

1. Instale o [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli)
2. Faça login:
```bash
heroku login
```
3. Crie o app:
```bash
heroku create seu-app-name
```
4. Configure buildpack:
```bash
heroku buildpacks:set heroku/python
```
5. Configure variáveis de ambiente:
```bash
heroku config:set PORT=8000
heroku config:set DOWNLOAD_DIR=/app/downloads
```
6. Deploy:
```bash
git push heroku main
```

### Outras Plataformas

O projeto também pode ser deployado em:
- **Vercel** (com adaptador para Python)
- **Fly.io** (com Dockerfile)
- **AWS Elastic Beanstalk**
- **Google Cloud Run**

## API Endpoints

### Health Check

```
GET /health
```

Retorna o status da API.

### Buscar Vídeos

```
POST /search
Body:
{
  "query": "nome da música ou artista",
  "max_results": 10
}
```

### Download/Streaming de Áudio

```
POST /download
Body:
{
  "video_id": "dQw4w9WgXcQ",
  "quality": "high",
  "mode": "download"  // ou "stream"
}
```

Qualidades disponíveis: `high` (320kbps), `medium` (192kbps), `low` (128kbps)

### Download de Arquivo

```
GET /files/{filename}
```

Retorna o arquivo MP3 baixado.

## Exemplos de Uso

### Buscar vídeos

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Rick Astley Never Gonna Give You Up",
    "max_results": 5
  }'
```

### Download de áudio

```bash
curl -X POST "http://localhost:8000/download" \
  -H "Content-Type: application/json" \
  -d '{
    "video_id": "dQw4w9WgXcQ",
    "quality": "high",
    "mode": "download"
  }'
```

### Streaming de áudio

```bash
curl -X POST "http://localhost:8000/download" \
  -H "Content-Type: application/json" \
  -d '{
    "video_id": "dQw4w9WgXcQ",
    "quality": "high",
    "mode": "stream"
  }'
```

## Documentação Interativa

Após iniciar a API, acesse:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## Segurança

- Em produção, use HTTPS e considere rate limiting

## Variáveis de Ambiente

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `HOST` | Host do servidor | `0.0.0.0` |
| `PORT` | Porta do servidor | `8000` |
| `DOWNLOAD_DIR` | Diretório de downloads | `./downloads` |

## Troubleshooting

### Erro: FFmpeg não encontrado

Certifique-se de que o FFmpeg está instalado:

**Linux/Mac:**
```bash
sudo apt-get install ffmpeg  # Debian/Ubuntu
brew install ffmpeg          # macOS
```

**Windows:**
Baixe do [site oficial](https://ffmpeg.org/download.html) e adicione ao PATH.

### Erro: Permissão negada

Verifique as permissões do diretório de downloads:
```bash
chmod 755 ./downloads
```

## Licença

Este projeto é fornecido como está para uso educacional e pessoal.
