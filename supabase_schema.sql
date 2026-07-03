-- ============================================================
-- ESQUEMA COMPLETO DO SUPABASE PARA O YOUTUBE SCRAPER API
-- Tabelas para armazenar dados de músicas, artistas, playlists,
-- downloads e estatísticas do scraper.
-- ============================================================

-- -----------------------------------------------------------
-- 1. Tabela: generos
--    Armazena os gêneros musicais para categorização
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS generos (
    id          TEXT PRIMARY KEY,
    nome        TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    descricao   TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Índice para busca por slug
CREATE INDEX IF NOT EXISTS idx_generos_slug ON generos(slug);

-- -----------------------------------------------------------
-- 2. Tabela: artistas
--    Armazena informações dos artistas/bandas
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS artistas (
    id              TEXT PRIMARY KEY,
    nome            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    biografia       TEXT,
    pais            TEXT,
    genero_id       TEXT REFERENCES generos(id) ON DELETE SET NULL,
    genero_nome     TEXT,
    imagem_url      TEXT,
    canal_youtube   TEXT,
    canal_id        TEXT,
    inscritos       BIGINT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para busca
CREATE INDEX IF NOT EXISTS idx_artistas_nome ON artistas(nome);
CREATE INDEX IF NOT EXISTS idx_artistas_slug ON artistas(slug);
CREATE INDEX IF NOT EXISTS idx_artistas_genero ON artistas(genero_id);

-- -----------------------------------------------------------
-- 3. Tabela: musicas
--    Armazena informações de cada música/vídeo do YouTube
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS musicas (
    id                  TEXT PRIMARY KEY,
    video_id            TEXT NOT NULL UNIQUE,        -- ID do vídeo no YouTube
    titulo              TEXT NOT NULL,
    descricao           TEXT,
    duracao_segundos    INTEGER DEFAULT 0,
    duracao_texto       TEXT,                        -- formato MM:SS
    thumbnail_url       TEXT,
    thumbnail_media     TEXT,                        -- média (mqdefault)
    thumbnail_max       TEXT,                        -- maxres (maxresdefault)
    url                 TEXT,                        -- URL completa do YouTube
    artista_id          TEXT REFERENCES artistas(id) ON DELETE SET NULL,
    artista_nome        TEXT,
    artista_slug        TEXT,
    genero_id           TEXT REFERENCES generos(id) ON DELETE SET NULL,
    genero_nome         TEXT,
    album               TEXT,
    release_year        INTEGER,
    views               BIGINT DEFAULT 0,
    likes               BIGINT DEFAULT 0,
    upload_date         TEXT,                        -- data de upload no YouTube (YYYYMMDD)
    upload_timestamp    TIMESTAMPTZ,
    
    -- URLs de mídia (preenchidas pelo scraper ou pelo service)
    stream_url          TEXT,                        -- URL para ouvir online (stream)
    download_url        TEXT,                        -- URL de download direto do áudio original
    download_ext        TEXT,                        -- extensão original (webm, m4a, opus)
    file_size_bytes     BIGINT DEFAULT 0,            -- tamanho do arquivo
    
    -- Metadados adicionais
    formato             TEXT,                        -- formato do áudio
    bitrate             INTEGER,                     -- bitrate em kbps
    sample_rate         INTEGER,                     -- sample rate
    
    -- Controle
    is_downloaded       BOOLEAN DEFAULT FALSE,       -- já foi baixado?
    is_processed        BOOLEAN DEFAULT FALSE,       -- já foi processado?
    last_checked        TIMESTAMPTZ,                 -- última verificação
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para busca e operações
CREATE INDEX IF NOT EXISTS idx_musicas_video_id ON musicas(video_id);
CREATE INDEX IF NOT EXISTS idx_musicas_titulo ON musicas(titulo);
CREATE INDEX IF NOT EXISTS idx_musicas_artista ON musicas(artista_id);
CREATE INDEX IF NOT EXISTS idx_musicas_genero ON musicas(genero_id);
CREATE INDEX IF NOT EXISTS idx_musicas_views ON musicas(views DESC);
CREATE INDEX IF NOT EXISTS idx_musicas_upload ON musicas(upload_date DESC);

-- Índice Full-Text Search para busca textual nos títulos
CREATE INDEX IF NOT EXISTS idx_musicas_titulo_fts 
ON musicas USING gin(to_tsvector('portuguese', titulo));

-- -----------------------------------------------------------
-- 4. Tabela: playlists
--    Armazena playlists do YouTube detectadas nas buscas
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS playlists (
    id                  TEXT PRIMARY KEY,
    playlist_id         TEXT NOT NULL UNIQUE,        -- ID da playlist no YouTube
    titulo              TEXT NOT NULL,
    descricao           TEXT,
    thumbnail_url       TEXT,
    url                 TEXT NOT NULL,               -- URL completa no YouTube
    canal_nome          TEXT,                        -- nome do canal que criou
    canal_id            TEXT,                        -- ID do canal
    video_count         INTEGER DEFAULT 0,           -- total de vídeos na playlist
    views               BIGINT DEFAULT 0,
    is_processed        BOOLEAN DEFAULT FALSE,       -- já processamos os itens?
    last_synced         TIMESTAMPTZ,                 -- última sincronização
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_playlists_playlist_id ON playlists(playlist_id);
CREATE INDEX IF NOT EXISTS idx_playlists_titulo ON playlists(titulo);

-- -----------------------------------------------------------
-- 5. Tabela: playlist_itens
--    Relaciona playlists com suas músicas (N para N)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS playlist_itens (
    id              TEXT PRIMARY KEY,
    playlist_id     TEXT NOT NULL REFERENCES playlists(playlist_id) ON DELETE CASCADE,
    musica_id       TEXT NOT NULL REFERENCES musicas(video_id) ON DELETE CASCADE,
    posicao         INTEGER DEFAULT 0,               -- posição na playlist
    added_at        TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(playlist_id, musica_id)
);

CREATE INDEX IF NOT EXISTS idx_playlist_itens_playlist ON playlist_itens(playlist_id);
CREATE INDEX IF NOT EXISTS idx_playlist_itens_musica ON playlist_itens(musica_id);

-- -----------------------------------------------------------
-- 6. Tabela: downloads
--    Histórico de downloads realizados
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS downloads (
    id              TEXT PRIMARY KEY,
    video_id        TEXT NOT NULL REFERENCES musicas(video_id) ON DELETE CASCADE,
    titulo          TEXT,
    artista_nome    TEXT,
    
    -- Informações do download
    url_origem      TEXT,                            -- URL usada para download
    formato_original TEXT,                           -- extensão original
    formato_convertido TEXT,                         -- formato para o qual foi convertido
    file_size_bytes BIGINT DEFAULT 0,
    file_path       TEXT,                            -- caminho no servidor
    duracao_segundos INTEGER DEFAULT 0,
    
    -- Modo
    modo            TEXT DEFAULT 'direct',            -- 'direct' ou 'server'
    origem          TEXT DEFAULT 'api',               -- 'api', 'playlist', 'scraper'
    
    -- Status
    status          TEXT DEFAULT 'success',           -- 'success', 'error', 'pending'
    erro            TEXT,
    
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_downloads_video ON downloads(video_id);
CREATE INDEX IF NOT EXISTS idx_downloads_data ON downloads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);

-- -----------------------------------------------------------
-- 7. Tabela: buscas
--    Log de todas as buscas realizadas (para analytics)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS buscas (
    id              TEXT PRIMARY KEY,
    query           TEXT NOT NULL,                   -- termo buscado
    tipo_detectado  TEXT,                            -- 'artist', 'music', 'playlist', 'general'
    modo            TEXT DEFAULT 'listen',            -- 'listen' ou 'download'
    resultados      INTEGER DEFAULT 0,               -- quantidade de resultados
    playlists_count INTEGER DEFAULT 0,               -- playlists encontradas
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_buscas_query ON buscas(query);
CREATE INDEX IF NOT EXISTS idx_buscas_data ON buscas(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_buscas_tipo ON buscas(tipo_detectado);

-- -----------------------------------------------------------
-- 8. Tabela: scraper_log
--    Log do scraper de sites de rádio/músicas
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS scraper_log (
    id              TEXT PRIMARY KEY,
    fonte           TEXT NOT NULL,                   -- 'radio_ao_vivo', etc.
    tipo            TEXT NOT NULL,                   -- 'genero', 'musica', 'artista'
    genero          TEXT,
    total_encontrado INTEGER DEFAULT 0,
    total_salvo     INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'success',           -- 'success', 'partial', 'error'
    erro            TEXT,
    executed_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraper_log_fonte ON scraper_log(fonte);
CREATE INDEX IF NOT EXISTS idx_scraper_log_data ON scraper_log(executed_at DESC);

-- -----------------------------------------------------------
-- 9. Tabela: estatisticas_artistas
--    Cache de estatísticas agregadas por artista
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS estatisticas_artistas (
    artista_id          TEXT PRIMARY KEY REFERENCES artistas(id) ON DELETE CASCADE,
    total_musicas       INTEGER DEFAULT 0,
    total_views         BIGINT DEFAULT 0,
    total_downloads     INTEGER DEFAULT 0,
    media_views         BIGINT DEFAULT 0,
    musica_mais_vista   TEXT,                        -- video_id
    musica_mais_vista_titulo TEXT,
    ultima_atualizacao  TIMESTAMPTZ DEFAULT NOW()
);

-- -----------------------------------------------------------
-- 10. VIEW: top_musicas
--     Visão das músicas mais populares
-- -----------------------------------------------------------
CREATE OR REPLACE VIEW top_musicas AS
SELECT 
    m.id,
    m.video_id,
    m.titulo,
    m.artista_nome,
    m.genero_nome,
    m.duracao_segundos,
    m.duracao_texto,
    m.thumbnail_url,
    m.views,
    m.likes,
    m.upload_date,
    m.stream_url,
    m.download_url,
    a.imagem_url AS artista_imagem,
    a.slug AS artista_slug
FROM musicas m
LEFT JOIN artistas a ON m.artista_id = a.id
WHERE m.views > 0
ORDER BY m.views DESC;

-- -----------------------------------------------------------
-- 11. VIEW: playlists_detalhadas
--     Visão das playlists com contagem de itens
-- -----------------------------------------------------------
CREATE OR REPLACE VIEW playlists_detalhadas AS
SELECT 
    p.id,
    p.playlist_id,
    p.titulo,
    p.descricao,
    p.thumbnail_url,
    p.url,
    p.canal_nome,
    p.video_count,
    p.views,
    COUNT(pi.id) AS itens_processados,
    p.last_synced,
    p.created_at
FROM playlists p
LEFT JOIN playlist_itens pi ON p.playlist_id = pi.playlist_id
GROUP BY p.id
ORDER BY p.video_count DESC;

-- -----------------------------------------------------------
-- 12. Função: atualizar_estatisticas_artista()
--     Trigger para manter estatísticas de artista atualizadas
-- -----------------------------------------------------------
CREATE OR REPLACE FUNCTION atualizar_estatisticas_artista()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO estatisticas_artistas (artista_id, total_musicas, total_views, ultima_atualizacao)
    SELECT 
        a.id,
        COUNT(m.id),
        COALESCE(SUM(m.views), 0),
        NOW()
    FROM artistas a
    LEFT JOIN musicas m ON m.artista_id = a.id
    WHERE a.id = COALESCE(NEW.artista_id, OLD.artista_id)
    GROUP BY a.id
    ON CONFLICT (artista_id) 
    DO UPDATE SET
        total_musicas = EXCLUDED.total_musicas,
        total_views = EXCLUDED.total_views,
        ultima_atualizacao = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger na tabela musicas
DROP TRIGGER IF EXISTS trg_atualizar_estatisticas ON musicas;
CREATE TRIGGER trg_atualizar_estatisticas
    AFTER INSERT OR UPDATE OF views, artista_id
    ON musicas
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_estatisticas_artista();

-- -----------------------------------------------------------
-- 13. Função: buscar_musicas(texto_busca)
--     Função de busca full-text search otimizada
-- -----------------------------------------------------------
CREATE OR REPLACE FUNCTION buscar_musicas(texto_busca TEXT)
RETURNS TABLE (
    id TEXT,
    video_id TEXT,
    titulo TEXT,
    artista_nome TEXT,
    genero_nome TEXT,
    duracao_segundos INTEGER,
    thumbnail_url TEXT,
    views BIGINT,
    url TEXT,
    stream_url TEXT,
    relevancia REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        m.id,
        m.video_id,
        m.titulo,
        m.artista_nome,
        m.genero_nome,
        m.duracao_segundos,
        m.thumbnail_url,
        m.views,
        m.url,
        m.stream_url,
        ts_rank(to_tsvector('portuguese', m.titulo || ' ' || COALESCE(m.artista_nome, '')), 
                plainto_tsquery('portuguese', texto_busca)) AS relevancia
    FROM musicas m
    WHERE 
        to_tsvector('portuguese', m.titulo || ' ' || COALESCE(m.artista_nome, '')) @@ 
        plainto_tsquery('portuguese', texto_busca)
        OR m.titulo ILIKE '%' || texto_busca || '%'
        OR m.artista_nome ILIKE '%' || texto_busca || '%'
    ORDER BY relevancia DESC, m.views DESC
    LIMIT 50;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------
-- 14. Configuração de Row Level Security (RLS)
--     Para ambientes com autenticação
-- -----------------------------------------------------------

-- Habilita RLS em todas as tabelas
ALTER TABLE generos ENABLE ROW LEVEL SECURITY;
ALTER TABLE artistas ENABLE ROW LEVEL SECURITY;
ALTER TABLE musicas ENABLE ROW LEVEL SECURITY;
ALTER TABLE playlists ENABLE ROW LEVEL SECURITY;
ALTER TABLE playlist_itens ENABLE ROW LEVEL SECURITY;
ALTER TABLE downloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE buscas ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraper_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE estatisticas_artistas ENABLE ROW LEVEL SECURITY;

-- Políticas: leitura pública para todos
CREATE POLICY "Leitura pública para generos" ON generos FOR SELECT USING (true);
CREATE POLICY "Leitura pública para artistas" ON artistas FOR SELECT USING (true);
CREATE POLICY "Leitura pública para musicas" ON musicas FOR SELECT USING (true);
CREATE POLICY "Leitura pública para playlists" ON playlists FOR SELECT USING (true);
CREATE POLICY "Leitura pública para playlist_itens" ON playlist_itens FOR SELECT USING (true);
CREATE POLICY "Leitura pública para downloads" ON downloads FOR SELECT USING (true);
CREATE POLICY "Leitura pública para estatisticas" ON estatisticas_artistas FOR SELECT USING (true);

-- Inserção apenas para usuários autenticados (ou service_role)
CREATE POLICY "Inserção autenticada para generos" ON generos FOR INSERT WITH CHECK (auth.role() = 'service_role' OR auth.role() = 'authenticated');
CREATE POLICY "Inserção autenticada para artistas" ON artistas FOR INSERT WITH CHECK (auth.role() = 'service_role' OR auth.role() = 'authenticated');
CREATE POLICY "Inserção autenticada para musicas" ON musicas FOR INSERT WITH CHECK (auth.role() = 'service_role' OR auth.role() = 'authenticated');
CREATE POLICY "Inserção autenticada para playlists" ON playlists FOR INSERT WITH CHECK (auth.role() = 'service_role' OR auth.role() = 'authenticated');
CREATE POLICY "Inserção autenticada para downloads" ON downloads FOR INSERT WITH CHECK (auth.role() = 'service_role' OR auth.role() = 'authenticated');
CREATE POLICY "Inserção autenticada para buscas" ON buscas FOR INSERT WITH CHECK (true); -- permite anônimo para analytics

-- -----------------------------------------------------------
-- 15. Índices adicionais para performance
-- -----------------------------------------------------------

-- Índice composto para consultas comuns
CREATE INDEX IF NOT EXISTS idx_musicas_artista_views 
ON musicas(artista_id, views DESC);

CREATE INDEX IF NOT EXISTS idx_musicas_genero_views 
ON musicas(genero_id, views DESC);

-- Índice para busca por artista + título
CREATE INDEX IF NOT EXISTS idx_musicas_artista_titulo 
ON musicas(artista_nome, titulo);

-- -----------------------------------------------------------
-- FIM DO ESQUEMA
-- ============================================================
-- Resumo das tabelas:
-- 1. generos             - Categorias musicais
-- 2. artistas            - Artistas/bandas
-- 3. musicas             - Músicas/vídeos (completa)
-- 4. playlists           - Playlists do YouTube
-- 5. playlist_itens      - Relação playlist-música
-- 6. downloads           - Histórico de downloads
-- 7. buscas              - Log de pesquisas
-- 8. scraper_log         - Log do scraper externo
-- 9. estatisticas_artistas - Cache de estatísticas
--
-- Views:
-- - top_musicas           - Músicas mais populares
-- - playlists_detalhadas  - Playlists completas
--
-- Funções:
-- - buscar_musicas()      - Full-text search
-- - atualizar_estatisticas_artista() - Trigger
-- ============================================================