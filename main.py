"""
API RESTful para scraping e processamento de mídia do YouTube.
Implementa endpoints de busca, download e streaming.
"""

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
from service import YouTubeService, AudioQuality, DownloadMode

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


@app.get(
    "/stream/{video_id}",
    tags=["Download"]
)
async def stream_audio(video_id: str, quality: AudioQuality = AudioQuality.HIGH):
    """
    Stream de áudio diretamente ao cliente sem salvar no disco.
    
    Args:
        video_id: ID do vídeo no YouTube
        quality: Qualidade do áudio (high, medium, low)
        
    Returns:
        StreamingResponse com o arquivo de áudio MP3
        
    Raises:
        HTTPException: Erro no streaming
    """
    try:
        # Obtém generator de streaming
        audio_generator = await youtube_service.stream_audio_to_client(
            video_id=video_id,
            quality=quality
        )
        
        return StreamingResponse(
            audio_generator,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f"attachment; filename={video_id}.mp3"
            }
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao fazer streaming de áudio: {str(e)}"
        )


@app.post(
    "/download",
    response_model=DownloadResponse,
    tags=["Download"]
)
async def download_audio(request: DownloadRequest):
    """
    Download de áudio em MP3 do YouTube.
    
    Args:
        request: Objeto com ID do vídeo, qualidade e modo de operação
        
    Returns:
        DownloadResponse com informações do arquivo baixado
        
    Raises:
        HTTPException: Erro no download
    """
    try:
        if request.mode == DownloadMode.DOWNLOAD:
            # Modo download: baixa o arquivo completo
            filepath, file_size, duration = await youtube_service.download_audio(
                video_id=request.video_id,
                quality=request.quality
            )
            
            # Retorna URL para download do arquivo
            download_url = f"/files/{request.video_id}.mp3"
            
            return DownloadResponse(
                success=True,
                message="Áudio baixado com sucesso",
                download_url=download_url,
                file_size=file_size,
                duration=duration
            )
        else:
            # Modo stream: retorna URL de streaming direto com informações de formato
            stream_info = await youtube_service.get_audio_stream_info(request.video_id)
            
            return DownloadResponse(
                success=True,
                message="Informações de streaming obtidas com sucesso",
                stream_url=stream_info['stream_url'],
                duration=stream_info['duration'],
                format=stream_info.get('format'),
                codec=stream_info.get('codec'),
                ext=stream_info.get('ext'),
                is_video_url=stream_info.get('is_video_url')
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
        filename: Nome do arquivo (ex: video_id.mp3)
        
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
        media_type="audio/mpeg",
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
