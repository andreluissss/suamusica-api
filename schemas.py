"""
Schemas Pydantic para validação de dados da API.
Define os modelos de entrada e saída para os endpoints.
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class VideoMetadata(BaseModel):
    """Metadados de um vídeo do YouTube."""
    video_id: str = Field(..., description="ID único do vídeo no YouTube")
    title: str = Field(..., description="Título do vídeo")
    thumbnail: str = Field(..., description="URL da miniatura do vídeo")
    duration: int = Field(..., description="Duração em segundos")
    url: str = Field(..., description="URL completa do vídeo")
    channel: Optional[str] = Field(None, description="Nome do canal")
    view_count: Optional[int] = Field(None, description="Número de visualizações")
    upload_date: Optional[str] = Field(None, description="Data de upload")
    result_type: Optional[str] = Field("video", description="Tipo do resultado: video, playlist")
    stream_url: Optional[str] = Field(None, description="URL direta do stream de áudio para ouvir online")


class PlaylistMetadata(BaseModel):
    """Metadados de uma playlist do YouTube."""
    playlist_id: str = Field(..., description="ID da playlist")
    title: str = Field(..., description="Título da playlist")
    thumbnail: Optional[str] = Field(None, description="URL da miniatura")
    channel: Optional[str] = Field(None, description="Nome do canal que criou a playlist")
    video_count: int = Field(0, description="Número de vídeos na playlist")
    url: str = Field(..., description="URL da playlist")
    result_type: str = Field("playlist", description="Sempre 'playlist'")


class SearchRequest(BaseModel):
    """Request para busca de vídeos."""
    query: str = Field(..., description="Termo de busca (artista, música, playlist, etc.)")
    max_results: Optional[int] = Field(10, description="Número máximo de resultados", ge=1, le=50)
    mode: Optional[str] = Field("listen", description="Modo: 'listen' para URL de stream, 'download' para URL de download original")
    include_playlists: Optional[bool] = Field(True, description="Incluir playlists nos resultados")
    type_filter: Optional[str] = Field("auto", description="Filtro: 'auto', 'video', 'playlist', 'music', 'artist'")


class SearchResponse(BaseModel):
    """Response da busca de vídeos."""
    success: bool = Field(..., description="Status da operação")
    results: List[VideoMetadata] = Field(default_factory=list, description="Lista de vídeos encontrados")
    playlists: List[PlaylistMetadata] = Field(default_factory=list, description="Lista de playlists encontradas")
    total: int = Field(..., description="Total de resultados")
    search_type: Optional[str] = Field(None, description="Tipo de busca detectada: artist, music, playlist, general")


class DownloadRequest(BaseModel):
    """Request para download de áudio."""
    video_id: str = Field(..., description="ID do vídeo no YouTube")
    format: Optional[str] = Field("original", description="Formato de saída: 'original' (sem conversão), 'mp3', 'm4a', 'webm'")
    download_mode: Optional[str] = Field("direct", description="Modo: 'direct' (URL direta), 'server' (processa no servidor)")


class DownloadResponse(BaseModel):
    """Response do download."""
    success: bool = Field(..., description="Status da operação")
    message: str = Field(..., description="Mensagem de status")
    download_url: Optional[str] = Field(None, description="URL para download do arquivo")
    file_size: Optional[int] = Field(None, description="Tamanho do arquivo em bytes")
    duration: Optional[int] = Field(None, description="Duração do áudio em segundos")
    format: Optional[str] = Field(None, description="Formato do arquivo")
    ext: Optional[str] = Field(None, description="Extensão do arquivo original")
    filename: Optional[str] = Field(None, description="Nome sugerido para o arquivo")
    title: Optional[str] = Field(None, description="Título da música")


class StreamUrlRequest(BaseModel):
    """Request para obter URL de stream de áudio."""
    video_id: str = Field(..., description="ID do vídeo no YouTube")


class StreamUrlResponse(BaseModel):
    """Response com URL de stream de áudio."""
    success: bool = Field(..., description="Status da operação")
    stream_url: Optional[str] = Field(None, description="URL direta do stream de áudio")
    title: Optional[str] = Field(None, description="Título do vídeo")
    duration: Optional[int] = Field(None, description="Duração em segundos")
    thumbnail: Optional[str] = Field(None, description="URL da miniatura")
    format: Optional[str] = Field(None, description="Formato do áudio")
    ext: Optional[str] = Field(None, description="Extensão do arquivo")


class PlaylistRequest(BaseModel):
    """Request para obter itens de uma playlist."""
    playlist_id: str = Field(..., description="ID da playlist no YouTube")
    max_results: Optional[int] = Field(50, description="Número máximo de vídeos", ge=1, le=200)


class PlaylistResponse(BaseModel):
    """Response com itens de uma playlist."""
    success: bool = Field(..., description="Status da operação")
    playlist_title: Optional[str] = Field(None, description="Título da playlist")
    playlist_url: Optional[str] = Field(None, description="URL da playlist")
    channel: Optional[str] = Field(None, description="Canal da playlist")
    video_count: int = Field(0, description="Total de vídeos na playlist")
    videos: List[VideoMetadata] = Field(default_factory=list, description="Lista de vídeos da playlist")


class PlaylistDownloadRequest(BaseModel):
    """Request para baixar todos os áudios de uma playlist."""
    playlist_id: str = Field(..., description="ID da playlist no YouTube")
    format: Optional[str] = Field("original", description="Formato de saída: 'original', 'mp3', 'm4a'")
    max_results: Optional[int] = Field(50, description="Número máximo de vídeos para baixar", ge=1, le=200)


class BatchDownloadResponse(BaseModel):
    """Response para download em lote (playlist)."""
    success: bool = Field(..., description="Status da operação")
    message: str = Field(..., description="Mensagem de status")
    total: int = Field(0, description="Total de músicas processadas")
    downloaded: int = Field(0, description="Quantas foram baixadas com sucesso")
    files: List[dict] = Field(default_factory=list, description="Lista de arquivos baixados")


class ErrorResponse(BaseModel):
    """Modelo de resposta de erro."""
    success: bool = Field(False, description="Sempre False para erros")
    error: str = Field(..., description="Mensagem de erro")
    detail: Optional[str] = Field(None, description="Detalhes adicionais do erro")