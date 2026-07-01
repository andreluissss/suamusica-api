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


class SearchRequest(BaseModel):
    """Request para busca de vídeos."""
    query: str = Field(..., description="Termo de busca (artista, música, playlist, etc.)")
    max_results: Optional[int] = Field(10, description="Número máximo de resultados", ge=1, le=50)


class SearchResponse(BaseModel):
    """Response da busca de vídeos."""
    success: bool = Field(..., description="Status da operação")
    results: List[VideoMetadata] = Field(..., description="Lista de vídeos encontrados")
    total: int = Field(..., description="Total de resultados")


class DownloadRequest(BaseModel):
    """Request para download de áudio."""
    video_id: str = Field(..., description="ID do vídeo no YouTube")
    format: Optional[str] = Field('mp3', description="Formato de saída (mp3, m4a, etc.)")


class DownloadResponse(BaseModel):
    """Response do download."""
    success: bool = Field(..., description="Status da operação")
    message: str = Field(..., description="Mensagem de status")
    download_url: Optional[str] = Field(None, description="URL para download do arquivo")
    file_size: Optional[int] = Field(None, description="Tamanho do arquivo em bytes")
    duration: Optional[int] = Field(None, description="Duração do áudio em segundos")
    format: Optional[str] = Field(None, description="Formato do arquivo")


class ErrorResponse(BaseModel):
    """Modelo de resposta de erro."""
    success: bool = Field(False, description="Sempre False para erros")
    error: str = Field(..., description="Mensagem de erro")
    detail: Optional[str] = Field(None, description="Detalhes adicionais do erro")
