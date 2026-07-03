"""
API RESTful para scraping e processamento de mídia do YouTube.
Implementa endpoints de busca inteligente, download, streaming e playlists.
"""

from fastapi import FastAPI, HTTPException, status, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from typing import Optional, List
import os
from dotenv import load_dotenv

from schemas import (
    SearchRequest, 
    SearchResponse, 
    DownloadRequest,
    DownloadResponse,
    StreamUrlRequest,
    StreamUrlResponse,
    PlaylistRequest,
    PlaylistResponse,
    PlaylistDownloadRequest,
    BatchDownloadResponse,
    ErrorResponse,
    VideoMetadata,
    PlaylistMetadata
)
from service import YouTubeService

# Carrega variáveis de ambiente
load_dotenv()

# Inicialização da aplicação
app = FastAPI(
    title="YouTube Media Processor API",
    description="API para busca inteligente, download e streaming de áudio do YouTube. "
                "Busca inteligente detecta artistas, músicas e playlists automaticamente "
                "(baseado no SanpTune). Suporta streaming online e download direto.",
    version="3.0.0"
)

# Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        "version": "3.0.0",
        "features": [
            "Busca inteligente com detecção de artista/música/playlist",
            "Stream de áudio para ouvir online",
            "Download direto de áudio original (sem conversão)",
            "Download com conversão (mp3, m4a, etc.)",
            "Suporte a playlists com download em lote"
        ]
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
    Busca inteligente no YouTube com detecção automática do tipo de busca.
    
    - Se pesquisar "Panda": retorna apenas músicas do artista Panda
    - Se pesquisar "Tubarões": retorna apenas músicas do Vitor Hugo e Tubarões
    - Se pesquisar "música - artista": busca específica da música
    - Se pesquisar "playlist": inclui playlists nos resultados
    
    Args:
        request: Objeto com termo de busca, modo (listen/download) e filtros
        
    Returns:
        SearchResponse com lista de vídeos, playlists e tipo de busca
    """
    try:
        results, playlists, search_type = await youtube_service.search_videos(
            query=request.query,
            max_results=request.max_results,
            mode=request.mode,
            include_playlists=request.include_playlists,
            type_filter=request.type_filter
        )
        
        return SearchResponse(
            success=True,
            results=results,
            playlists=playlists,
            total=len(results) + len(playlists),
            search_type=search_type
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar vídeos: {str(e)}"
        )


@app.post(
    "/playlist",
    response_model=PlaylistResponse,
    tags=["Playlist"]
)
async def get_playlist(request: PlaylistRequest):
    """
    Obtém todos os itens de uma playlist do YouTube.
    
    Args:
        request: Objeto com ID da playlist e número máximo de resultados
        
    Returns:
        PlaylistResponse com metadados da playlist e lista de vídeos
    """
    try:
        playlist_title, playlist_url, channel, total, videos = await youtube_service.get_playlist_items(
            playlist_id=request.playlist_id,
            max_results=request.max_results
        )
        
        # Anexa URLs de stream para cada vídeo (modo listen)
        videos = youtube_service._attach_stream_urls(videos)
        
        return PlaylistResponse(
            success=True,
            playlist_title=playlist_title,
            playlist_url=playlist_url,
            channel=channel,
            video_count=total,
            videos=videos
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter playlist: {str(e)}"
        )


@app.post(
    "/playlist/download",
    response_model=BatchDownloadResponse,
    tags=["Playlist"]
)
async def download_playlist(request: PlaylistDownloadRequest):
    """
    Baixa todos os áudios de uma playlist no formato original ou convertido.
    
    Args:
        request: Objeto com ID da playlist, formato e limite
        
    Returns:
        BatchDownloadResponse com resultados de todos os downloads
    """
    try:
        # Primeiro obtém os itens da playlist
        playlist_title, playlist_url, channel, total, videos = await youtube_service.get_playlist_items(
            playlist_id=request.playlist_id,
            max_results=request.max_results
        )
        
        if not videos:
            return BatchDownloadResponse(
                success=True,
                message="Playlist vazia ou não encontrada",
                total=0,
                downloaded=0,
                files=[]
            )
        
        # IDs dos vídeos para baixar
        video_ids = [v.video_id for v in videos if v.video_id]
        
        # Baixa todos em lote
        results = await youtube_service.download_batch(
            video_ids=video_ids,
            output_format=request.format
        )
        
        downloaded_count = sum(1 for r in results if r.get('success'))
        
        return BatchDownloadResponse(
            success=True,
            message=f"Playlist '{playlist_title}': {downloaded_count} de {len(results)} músicas baixadas",
            total=len(results),
            downloaded=downloaded_count,
            files=results
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao baixar playlist: {str(e)}"
        )


@app.post(
    "/download",
    response_model=DownloadResponse,
    tags=["Download"]
)
async def download_audio(request: DownloadRequest):
    """
    Baixa áudio do YouTube no formato original ou converte usando FFmpeg.
    
    Modos:
    - Modo 'direct' (padrão): retorna URL direta do áudio original sem processar no servidor
    - Modo 'server': baixa e processa no servidor, retorna link para download
    
    Formatos:
    - 'original': mantém o formato original do servidor (webm, m4a, opus)
    - 'mp3': converte para MP3 (requer FFmpeg)
    - 'm4a': converte para M4A AAC (requer FFmpeg)
    
    Args:
        request: Objeto com ID do vídeo, formato e modo de download
        
    Returns:
        DownloadResponse com informações do arquivo baixado
    """
    try:
        if request.download_mode == 'direct':
            # Modo direto: retorna URL de download sem processar no servidor
            result = await youtube_service.get_direct_download_url(
                video_id=request.video_id
            )
            
            filename = f"{result.get('title', 'audio')}.{result.get('ext', 'webm')}"
            # Sanitiza nome do arquivo
            filename = "".join(c for c in filename if c.isalnum() or c in ' ._-()').strip()[:100]
            
            return DownloadResponse(
                success=True,
                message=f"URL de download direto obtida: {result.get('ext', 'original')}",
                download_url=result.get('download_url'),
                file_size=0,
                duration=result.get('duration', 0),
                format=result.get('ext', 'original'),
                ext=result.get('ext'),
                filename=filename,
                title=result.get('title')
            )
        else:
            # Modo servidor: baixa e processa no servidor
            filepath, file_size, duration, ext = await youtube_service.download_audio(
                video_id=request.video_id,
                output_format=request.format if request.format != 'original' else 'original'
            )
            
            filename = os.path.basename(filepath)
            download_url = f"/files/{filename}"
            
            return DownloadResponse(
                success=True,
                message=f"Áudio baixado{' e convertido para ' + request.format if request.format != 'original' else ' no formato original'}",
                download_url=download_url,
                file_size=file_size,
                duration=duration,
                format=request.format if request.format != 'original' else ext,
                ext=ext,
                filename=filename
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao baixar/converter áudio: {str(e)}"
        )


@app.post(
    "/stream-url",
    response_model=StreamUrlResponse,
    tags=["Stream"]
)
async def get_stream_url(request: StreamUrlRequest):
    """
    Obtém a URL direta do stream de áudio do YouTube para ouvir online.
    Não baixa nada no servidor, apenas retorna a URL do áudio.
    
    Args:
        request: Objeto com ID do vídeo
        
    Returns:
        StreamUrlResponse com a URL direta do stream de áudio
    """
    try:
        result = await youtube_service.get_audio_stream_url(
            video_id=request.video_id
        )
        
        return StreamUrlResponse(
            success=True,
            stream_url=result.get('stream_url'),
            title=result.get('title'),
            duration=result.get('duration'),
            thumbnail=result.get('thumbnail'),
            format=result.get('format'),
            ext=result.get('ext')
        )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter URL de stream: {str(e)}"
        )


@app.get(
    "/files/{filename}",
    tags=["Files"]
)
async def get_file(filename: str):
    """
    Endpoint para download de arquivos processados no servidor.
    
    Args:
        filename: Nome do arquivo
        
    Returns:
        FileResponse com o arquivo solicitado
    """
    file_path = youtube_service.download_dir / filename
    
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo não encontrado"
        )
    
    media_type = "audio/mpeg"
    if filename.endswith('.m4a'):
        media_type = "audio/mp4"
    elif filename.endswith('.webm'):
        media_type = "audio/webm"
    elif filename.endswith('.opus'):
        media_type = "audio/opus"
    elif filename.endswith('.ogg'):
        media_type = "audio/ogg"
    
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
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