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


class ErrorResponse(BaseModel):
    """Modelo de resposta de erro."""
    success: bool = Field(False, description="Sempre False para erros")
    error: str = Field(..., description="Mensagem de erro")
    detail: Optional[str] = Field(None, description="Detalhes adicionais do erro")
