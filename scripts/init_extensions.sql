-- PostgreSQL扩展初始化脚本
-- 该文件会在容器启动时自动执行

-- 连接到qgis数据库
\c qgis_db;

-- 启用PostGIS扩展（空间数据支持）
CREATE EXTENSION IF NOT EXISTS postgis;

-- 启用pgvector扩展（向量相似度搜索）
CREATE EXTENSION IF NOT EXISTS vector;

-- 启用pg_trgm扩展（三元组文本匹配）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 验证扩展是否安装成功
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('postgis', 'vector', 'pg_trgm');
