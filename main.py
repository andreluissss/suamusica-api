"""
API RESTful para scraping e processamento de mídia do YouTube.
Implementa endpoints de busca, download e streaming.
"""

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from typing import Optional
import os
from dotenv import load_dotenv

from schemas import (
    SearchRequest, 
    SearchResponse, 
    DownloadRequest,
    DownloadResponse,
    ErrorResponse,
    VideoMetadata
)
from service import YouTubeService

# Carrega variáveis de ambiente
load_dotenv()

# Inicialização da aplicação
app = FastAPI(
    title="YouTube Media Processor API",
    description="API para busca, download e streaming de áudio do YouTube",
    version="1.0.0"
)

# Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, especifique as origens permitidas
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# Inicialização do serviço
youtube_service = YouTubeService(download_dir=os.getenv("DOWNLOAD_DIR", "./downloads"))


@app.get("/", tags=["Health"])
async def root():
    """Endpoint raiz para verificação de status da API."""
    return {
        "status": "online",
        "service": "YouTube Media Processor API",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Endpoint de health check para monitoramento."""
    return {"status": "healthy"}


@app.post(
    "/search", 
    response_model=SearchResponse,
    tags=["Search"]
)
async def search_videos(request: SearchRequest):
    """
    Busca vídeos no YouTube.
    
    Args:
        request: Objeto com termo de busca e número máximo de resultados
        
    Returns:
        SearchResponse com lista de vídeos encontrados
        
    Raises:
        HTTPException: Erro na busca
    """
    try:
        results = await youtube_service.search_videos(
            query=request.query,
            max_results=request.max_results
        )
        
        return SearchResponse(
            success=True,
            results=results,
            total=len(results)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar vídeos: {str(e)}"
        )


@app.post(
    "/download",
    response_model=DownloadResponse,
    tags=["Download"]
)
async def download_audio(request: DownloadRequest):
    """
    Download de áudio em M4A (formato original do YouTube).
    Não usa conversão FFmpeg para funcionar no Railway.
    
    Args:
        request: Objeto com ID do vídeo
        
    Returns:
        DownloadResponse com informações do arquivo baixado
        
    Raises:
        HTTPException: Erro no download
    """
    try:
        # Baixa o arquivo no formato original (M4A)
        filepath, file_size, duration = await youtube_service.download_audio(
            video_id=request.video_id
        )
        
        # Retorna URL para download do arquivo
        filename = os.path.basename(filepath)
        download_url = f"/files/{filename}"
        
        return DownloadResponse(
            success=True,
            message="Áudio baixado com sucesso (formato M4A)",
            download_url=download_url,
            file_size=file_size,
            duration=duration,
            format="m4a"
        )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao processar áudio: {str(e)}"
        )


@app.get(
    "/files/{filename}",
    tags=["Files"]
)
async def get_file(filename: str):
    """
    Endpoint para download de arquivos processados.
    
    Args:
        filename: Nome do arquivo (ex: video_id.m4a)
        
    Returns:
        FileResponse com o arquivo solicitado
        
    Raises:
        HTTPException: Arquivo não encontrado
    """
    file_path = youtube_service.download_dir / filename
    
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo não encontrado"
        )
    
    return FileResponse(
        path=str(file_path),
        media_type="audio/mp4",
        filename=filename
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handler personalizado para exceções HTTP."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            success=False,
            error=exc.detail,
            detail=f"HTTP {exc.status_code}"
        ).model_dump()
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handler personalizado para erros de validação."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            success=False,
            error="Erro de validação",
            detail=str(exc)
        ).model_dump()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handler personalizado para exceções gerais."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            success=False,
            error="Erro interno do servidor",
            detail=str(exc)
        ).model_dump()
    )


if __name__ == "__main__":
    import uvicorn
    
    # Configurações do servidor
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
        access_log=True
    )
